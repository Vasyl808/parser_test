"""Sync raw parser rows into the unified shopping catalog."""

from __future__ import annotations

import os
from typing import Any, Iterable

from dotenv import load_dotenv
from supabase import Client, create_client

from catalog_normalization import (
    calculate_price_per_unit,
    choose_primary_category,
    make_canonical_key,
    normalize_brand,
    normalize_product_name,
    normalize_text,
    normalize_weight,
    split_category_names,
    stable_store_sku,
)


DEFAULT_BATCH_SIZE = 500
ATB_STORE = {"name": "ATB", "slug": "atb"}
SILPO_STORE = {"name": "Silpo", "slug": "silpo"}


def _decimal_to_db(value: Any) -> Any:
    if value is None:
        return None
    return str(value)


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "так"}
    return bool(value)


def get_supabase_client_from_env() -> Client:
    load_dotenv()
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables must be set")
    return create_client(supabase_url, supabase_key)


def _execute_upsert(client: Client, table: str, rows: list[dict[str, Any]], on_conflict: str):
    if not rows:
        return []
    response = client.table(table).upsert(rows, on_conflict=on_conflict).execute()
    return response.data or []


def _chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def ensure_store(client: Client, slug: str, name: str) -> dict[str, Any]:
    existing = client.table("stores").select("*").eq("slug", slug).limit(1).execute()
    if existing.data:
        return existing.data[0]

    created = client.table("stores").insert({"slug": slug, "name": name}).execute()
    if not created.data:
        raise RuntimeError(f"Could not create store {slug}")
    return created.data[0]


def ensure_categories(
    client: Client,
    store_id: int,
    raw_category_names: Iterable[str],
) -> dict[str, dict[str, Any]]:
    by_normalized: dict[str, dict[str, Any]] = {}
    unique_names: dict[str, str] = {}

    for raw_name in raw_category_names:
        normalized = normalize_text(raw_name)
        if normalized:
            unique_names.setdefault(normalized, raw_name)

    for normalized_name, raw_name in unique_names.items():
        existing = (
            client.table("canonical_categories")
            .select("*")
            .eq("normalized_name", normalized_name)
            .limit(1)
            .execute()
        )
        if existing.data:
            category = existing.data[0]
        else:
            created = (
                client.table("canonical_categories")
                .insert({"name": raw_name, "normalized_name": normalized_name})
                .execute()
            )
            if not created.data:
                raise RuntimeError(f"Could not create category {raw_name}")
            category = created.data[0]

        by_normalized[normalized_name] = category

        alias_row = {
            "canonical_category_id": category["id"],
            "store_id": store_id,
            "raw_category_name": raw_name,
            "normalized_raw_category_name": normalized_name,
        }
        _execute_upsert(
            client,
            "category_aliases",
            [alias_row],
            on_conflict="store_id,normalized_raw_category_name",
        )

    return by_normalized


def _build_store_product_row(
    raw: dict[str, Any],
    store_id: int,
    category_id: int | None,
    primary_category: str,
    source_table: str = "atb_products",
) -> dict[str, Any] | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None

    normalized_name = normalize_product_name(name)
    normalized_brand = normalize_brand(raw.get("brand"))
    normalized_weight, normalized_unit = normalize_weight(
        raw.get("weight"),
        raw.get("unit"),
        fallback_name=name,
    )
    price_per_unit = calculate_price_per_unit(raw.get("current_price"), normalized_weight)

    return {
        "store_id": store_id,
        "store_sku": stable_store_sku(raw),
        "source_table": source_table,
        "name": name,
        "brand": str(raw.get("brand") or "").strip() or None,
        "weight": str(raw.get("weight") or "").strip() or None,
        "unit": str(raw.get("unit") or "").strip() or None,
        "normalized_name": normalized_name or normalize_text(name),
        "normalized_brand": normalized_brand or None,
        "normalized_weight": _decimal_to_db(normalized_weight),
        "normalized_unit": normalized_unit or None,
        "price_per_unit": _decimal_to_db(price_per_unit),
        "url": raw.get("url") or None,
        "current_price": raw.get("current_price"),
        "regular_price": raw.get("regular_price"),
        "discount": str(raw.get("discount") or "").strip() or None,
        "is_promo": _bool(raw.get("is_promo")),
        "is_available": _bool(raw.get("is_available"), default=True),
        "is_economy": _bool(raw.get("is_economy")),
        "raw_category_name": primary_category,
        "canonical_category_id": category_id,
    }


def _canonical_row_from_store_product(row: dict[str, Any]) -> dict[str, Any]:
    canonical_key = make_canonical_key(
        row.get("canonical_category_id"),
        row.get("normalized_brand") or "",
        row.get("normalized_name") or "",
        row.get("normalized_weight"),
        row.get("normalized_unit") or "",
    )
    return {
        "canonical_key": canonical_key,
        "canonical_name": row["name"],
        "brand": row.get("brand"),
        "normalized_name": row["normalized_name"],
        "normalized_brand": row.get("normalized_brand"),
        "normalized_weight": row.get("normalized_weight"),
        "normalized_unit": row.get("normalized_unit"),
        "category_id": row.get("canonical_category_id"),
    }


def sync_products_to_unified_catalog(
    client: Client,
    products: list[dict[str, Any]],
    store_slug: str,
    store_name: str,
    source_table: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, int]:
    """Generic sync: works for any store (ATB, Silpo, etc.)."""
    store = ensure_store(client, store_slug, store_name)
    store_id = store["id"]

    all_category_names: list[str] = []
    primary_category_by_sku: dict[str, str] = {}

    for raw in products:
        categories = split_category_names(raw.get("category_name"))
        primary = choose_primary_category(categories)
        all_category_names.extend(categories or [primary])
        primary_category_by_sku[stable_store_sku(raw)] = primary

    categories_by_normalized = ensure_categories(client, store_id, all_category_names)

    store_rows: list[dict[str, Any]] = []
    for raw in products:
        store_sku = stable_store_sku(raw)
        primary_category = primary_category_by_sku.get(store_sku, "Без категорії")
        category = categories_by_normalized.get(normalize_text(primary_category))
        row = _build_store_product_row(
            raw,
            store_id=store_id,
            category_id=category["id"] if category else None,
            primary_category=primary_category,
            source_table=source_table,
        )
        if row:
            store_rows.append(row)

    stored_product_rows: list[dict[str, Any]] = []
    for batch in _chunks(store_rows, batch_size):
        stored_product_rows.extend(
            _execute_upsert(
                client,
                "store_products",
                batch,
                on_conflict="store_id,store_sku",
            )
        )

    if len(stored_product_rows) < len(store_rows):
        stored_product_rows = fetch_store_products_by_skus(
            client,
            store_id,
            [row["store_sku"] for row in store_rows],
            batch_size=batch_size,
        )

    canonical_by_key: dict[str, dict[str, Any]] = {}
    for row in stored_product_rows:
        canonical = _canonical_row_from_store_product(row)
        canonical_by_key[canonical["canonical_key"]] = canonical

    stored_canonical_rows: list[dict[str, Any]] = []
    canonical_rows = list(canonical_by_key.values())
    for batch in _chunks(canonical_rows, batch_size):
        stored_canonical_rows.extend(
            _execute_upsert(
                client,
                "canonical_products",
                batch,
                on_conflict="canonical_key",
            )
        )

    canonical_id_by_key = {
        row["canonical_key"]: row["id"]
        for row in stored_canonical_rows
        if row.get("canonical_key") and row.get("id")
    }
    if len(canonical_id_by_key) < len(canonical_rows):
        canonical_id_by_key.update(
            fetch_canonical_ids_by_keys(
                client,
                [row["canonical_key"] for row in canonical_rows],
                batch_size=batch_size,
            )
        )

    match_rows: list[dict[str, Any]] = []
    for row in stored_product_rows:
        canonical_key = _canonical_row_from_store_product(row)["canonical_key"]
        canonical_id = canonical_id_by_key.get(canonical_key)
        if not canonical_id:
            continue
        match_rows.append(
            {
                "canonical_product_id": canonical_id,
                "store_product_id": row["id"],
                "match_score": "1.0",
                "match_method": "same_store_seed",
                "is_verified": False,
            }
        )

    for batch in _chunks(match_rows, batch_size):
        _execute_upsert(
            client,
            "product_matches",
            batch,
            on_conflict="store_product_id",
        )

    return {
        "stores": 1,
        "categories": len(categories_by_normalized),
        "store_products": len(store_rows),
        "canonical_products": len(canonical_rows),
        "product_matches": len(match_rows),
    }


def sync_atb_products_to_unified_catalog(
    client: Client,
    products: list[dict[str, Any]],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, int]:
    """ATB-specific wrapper for backwards compatibility."""
    return sync_products_to_unified_catalog(
        client, products,
        store_slug=ATB_STORE["slug"],
        store_name=ATB_STORE["name"],
        source_table="atb_products",
        batch_size=batch_size,
    )


def sync_silpo_products_to_unified_catalog(
    client: Client,
    products: list[dict[str, Any]],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, int]:
    """Silpo-specific wrapper."""
    return sync_products_to_unified_catalog(
        client, products,
        store_slug=SILPO_STORE["slug"],
        store_name=SILPO_STORE["name"],
        source_table="silpo_products",
        batch_size=batch_size,
    )


def fetch_store_products_by_skus(
    client: Client,
    store_id: int,
    skus: list[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch in _chunks(skus, batch_size):
        response = (
            client.table("store_products")
            .select("*")
            .eq("store_id", store_id)
            .in_("store_sku", batch)
            .execute()
        )
        rows.extend(response.data or [])
    return rows


def fetch_canonical_ids_by_keys(
    client: Client,
    keys: list[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, int]:
    ids: dict[str, int] = {}
    for batch in _chunks(keys, batch_size):
        response = (
            client.table("canonical_products")
            .select("id,canonical_key")
            .in_("canonical_key", batch)
            .execute()
        )
        for row in response.data or []:
            ids[row["canonical_key"]] = row["id"]
    return ids


def _fetch_all_from_table(client: Client, table: str, page_size: int = 1000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        response = (
            client.table(table)
            .select("*")
            .range(start, start + page_size - 1)
            .execute()
        )
        page = response.data or []
        rows.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    return rows


def fetch_all_atb_products(client: Client, page_size: int = 1000) -> list[dict[str, Any]]:
    return _fetch_all_from_table(client, "atb_products", page_size)


def fetch_all_silpo_products(client: Client, page_size: int = 1000) -> list[dict[str, Any]]:
    return _fetch_all_from_table(client, "silpo_products", page_size)


def sync_existing_atb_products() -> dict[str, int]:
    client = get_supabase_client_from_env()
    products = fetch_all_atb_products(client)
    return sync_atb_products_to_unified_catalog(client, products)


def sync_existing_silpo_products() -> dict[str, int]:
    client = get_supabase_client_from_env()
    products = fetch_all_silpo_products(client)
    return sync_silpo_products_to_unified_catalog(client, products)
