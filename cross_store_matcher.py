#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-store product matcher.

Runs AFTER both ATB and Silpo sync scripts have populated the unified catalog.
Finds products that exist in both stores by matching on:
  - normalized_name (token-level similarity >= threshold)
  - normalized_weight (numeric closeness, since units differ between stores)

When a match is found, both store_products point to the SAME canonical_product_id
so the shopping_products view can compare prices across stores.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SIMILARITY_THRESHOLD = 0.65  # 65% token overlap to consider a match
WEIGHT_TOLERANCE = 0.02      # Allow 2% difference in weight (rounding)
BATCH_SIZE = 500
# ---------------------------------------------------------------------------


def get_client() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(url, key)


def _tokenize(text: str) -> set[str]:
    """Split normalized name into meaningful tokens."""
    if not text:
        return set()
    return {t for t in text.lower().split() if len(t) > 1 and not t.replace(".", "").isdigit()}


def _similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _weight_close(w1: float, w2: float) -> bool:
    """Check if two weights are within WEIGHT_TOLERANCE of each other."""
    if w1 == 0 and w2 == 0:
        return True
    avg = (w1 + w2) / 2
    if avg == 0:
        return False
    return abs(w1 - w2) / avg <= WEIGHT_TOLERANCE


def _safe_float(val: Any) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def fetch_products_for_matching(client: Client, store_id: int) -> list[dict[str, Any]]:
    """Fetch store_products needed for matching."""
    rows: list[dict[str, Any]] = []
    start = 0
    page_size = 1000
    while True:
        response = (
            client.table("store_products")
            .select("id,normalized_name,normalized_brand,normalized_weight,normalized_unit")
            .eq("store_id", store_id)
            .range(start, start + page_size - 1)
            .execute()
        )
        page = response.data or []
        rows.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    return rows


def fetch_current_matches(client: Client) -> dict[int, int]:
    """Fetch existing product_matches: store_product_id -> canonical_product_id."""
    mapping: dict[int, int] = {}
    start = 0
    page_size = 1000
    while True:
        response = (
            client.table("product_matches")
            .select("store_product_id,canonical_product_id")
            .range(start, start + page_size - 1)
            .execute()
        )
        page = response.data or []
        for row in page:
            mapping[row["store_product_id"]] = row["canonical_product_id"]
        if len(page) < page_size:
            break
        start += page_size
    return mapping


def _weight_bucket(w: float) -> int:
    """Bucket weight to nearest 10g (0.01kg) for fast indexing."""
    return round(w * 100)


def run_cross_store_matching() -> dict[str, int]:
    client = get_client()

    # Get store IDs
    stores = client.table("stores").select("id,slug").execute()
    store_map = {s["slug"]: s["id"] for s in (stores.data or [])}
    atb_id = store_map.get("atb")
    silpo_id = store_map.get("silpo")
    if not atb_id or not silpo_id:
        print("ERROR: Need both 'atb' and 'silpo' stores")
        return {"error": 1}

    print("[1/5] Fetching ATB products...")
    atb_products = fetch_products_for_matching(client, atb_id)
    print(f"  ATB: {len(atb_products)} products")

    print("[2/5] Fetching Silpo products...")
    silpo_products = fetch_products_for_matching(client, silpo_id)
    print(f"  Silpo: {len(silpo_products)} products")

    print("[3/5] Fetching current product_matches...")
    current_matches = fetch_current_matches(client)
    print(f"  Existing matches: {len(current_matches)}")

    # Index Silpo products by weight bucket for fast lookup
    print("[4/5] Building index and matching...")
    silpo_by_bucket: dict[int, list[dict]] = {}
    for sp in silpo_products:
        w = _safe_float(sp.get("normalized_weight"))
        if w > 0:
            bucket = _weight_bucket(w)
            # Add to this bucket and adjacent buckets for tolerance
            for b in (bucket - 1, bucket, bucket + 1):
                silpo_by_bucket.setdefault(b, []).append(sp)

    updates: list[dict[str, Any]] = []
    matched_count = 0
    match_examples: list[str] = []

    for i, atb_row in enumerate(atb_products):
        if (i + 1) % 1000 == 0:
            print(f"  Processed {i+1}/{len(atb_products)}... ({matched_count} matches)")

        atb_w = _safe_float(atb_row.get("normalized_weight"))
        if atb_w <= 0:
            continue

        atb_tokens = _tokenize(atb_row.get("normalized_name", ""))
        if not atb_tokens:
            continue

        atb_brand = (atb_row.get("normalized_brand") or "").strip().lower()
        bucket = _weight_bucket(atb_w)
        candidates = silpo_by_bucket.get(bucket, [])

        best_score = 0.0
        best_silpo = None

        for silpo_row in candidates:
            silpo_w = _safe_float(silpo_row.get("normalized_weight"))

            # Weight must be close
            if not _weight_close(atb_w, silpo_w):
                continue

            silpo_brand = (silpo_row.get("normalized_brand") or "").strip().lower()

            # Brand mismatch filter (only if BOTH have brand)
            if atb_brand and silpo_brand and atb_brand != silpo_brand:
                continue

            silpo_tokens = _tokenize(silpo_row.get("normalized_name", ""))
            score = _similarity(atb_tokens, silpo_tokens)

            # Boost score if brands match
            if atb_brand and silpo_brand and atb_brand == silpo_brand:
                score = min(1.0, score + 0.15)

            if score > best_score:
                best_score = score
                best_silpo = silpo_row

        if best_score >= SIMILARITY_THRESHOLD and best_silpo:
            matched_count += 1
            atb_sp_id = atb_row["id"]
            silpo_sp_id = best_silpo["id"]

            if matched_count <= 10:
                match_examples.append(
                    f"  ATB: {atb_row.get('normalized_name', '')[:40]} ({atb_w}kg) <-> "
                    f"Silpo: {best_silpo.get('normalized_name', '')[:40]} ({_safe_float(best_silpo.get('normalized_weight'))}kg) "
                    f"[score={best_score:.2f}]"
                )

            atb_canonical = current_matches.get(atb_sp_id)
            silpo_canonical = current_matches.get(silpo_sp_id)

            if atb_canonical and silpo_canonical:
                target = min(atb_canonical, silpo_canonical)
                if silpo_canonical != target:
                    updates.append({
                        "store_product_id": silpo_sp_id,
                        "canonical_product_id": target,
                        "match_score": str(round(best_score, 4)),
                        "match_method": "cross_store_name_weight",
                        "is_verified": False,
                    })
                if atb_canonical != target:
                    updates.append({
                        "store_product_id": atb_sp_id,
                        "canonical_product_id": target,
                        "match_score": str(round(best_score, 4)),
                        "match_method": "cross_store_name_weight",
                        "is_verified": False,
                    })
            elif atb_canonical:
                updates.append({
                    "store_product_id": silpo_sp_id,
                    "canonical_product_id": atb_canonical,
                    "match_score": str(round(best_score, 4)),
                    "match_method": "cross_store_name_weight",
                    "is_verified": False,
                })
            elif silpo_canonical:
                updates.append({
                    "store_product_id": atb_sp_id,
                    "canonical_product_id": silpo_canonical,
                    "match_score": str(round(best_score, 4)),
                    "match_method": "cross_store_name_weight",
                    "is_verified": False,
                })

    print(f"\n  Total cross-store matches: {matched_count}")
    if match_examples:
        print("  Example matches:")
        for ex in match_examples:
            print(ex)
    # Deduplicate by store_product_id (keep the last/best match)
    deduped: dict[int, dict] = {}
    for u in updates:
        deduped[u["store_product_id"]] = u
    updates = list(deduped.values())

    print(f"  product_matches rows to update: {len(updates)}")

    # Upsert
    print("[5/5] Upserting cross-store matches...")
    upserted = 0
    for i in range(0, len(updates), BATCH_SIZE):
        batch = updates[i : i + BATCH_SIZE]
        client.table("product_matches").upsert(batch, on_conflict="store_product_id").execute()
        upserted += len(batch)
        print(f"  Upserted {upserted}/{len(updates)}")

    return {
        "atb_products": len(atb_products),
        "silpo_products": len(silpo_products),
        "cross_store_matches": matched_count,
        "rows_updated": len(updates),
    }


if __name__ == "__main__":
    stats = run_cross_store_matching()
    print("\n" + "=" * 60)
    print("Cross-store matching complete")
    print("=" * 60)
    for k, v in stats.items():
        print(f"  {k}: {v}")
