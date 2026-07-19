"""
Migration: recalculate discount column as percent for ALL store_products
where current_price and regular_price are available.

Run with:
    .\.venv\Scripts\python.exe migrate_discount.py
"""
from __future__ import annotations
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

client = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])

BATCH = 1000
updated = 0
skipped = 0
page = 0

print("Scanning ALL store_products with prices to fix discount...")

while True:
    # Stable pagination with explicit order by id
    res = (
        client.table("store_products")
        .select("id, current_price, regular_price, discount")
        .not_.is_("current_price", "null")
        .not_.is_("regular_price", "null")
        .order("id")
        .range(page * BATCH, (page + 1) * BATCH - 1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        break

    page_updated = 0
    for r in rows:
        try:
            cp_f = float(r["current_price"])
            rp_f = float(r["regular_price"])
        except (TypeError, ValueError):
            skipped += 1
            continue

        if rp_f > cp_f > 0:
            pct = str(round((rp_f - cp_f) / rp_f * 100))
        else:
            skipped += 1
            continue

        current_disc = str(r.get("discount") or "").strip()
        if current_disc != pct:
            client.table("store_products").update({"discount": pct}).eq("id", r["id"]).execute()
            page_updated += 1
            updated += 1
        else:
            skipped += 1

    if page_updated > 0 or page % 10 == 0:
        print(f"  Page {page}: updated {page_updated} (total: {updated})")
    page += 1

print(f"\nDone. Total updated: {updated}, Skipped: {skipped}")
