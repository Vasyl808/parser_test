# -*- coding: utf-8 -*-
"""
Повноцінний парсер ATB Market — всі категорії -> Supabase.

Що робить:
  1. Спочатку парсить категорію "Економія" (https://www.atbmarket.com/catalog/economy),
     позначаючи товари is_economy=True.
  2. Знаходить усі інші категорію через sitemap XML.
  3. Парсить кожну категорію посторінково.
  4. Дедублікує товари за SKU (O(1) через set).
  5. Зберігає результат у Supabase (таблиця atb_products) та в atb_full.csv.

Використання:
    python atb_parser.py
"""
import csv
import io
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from dotenv import load_dotenv
from supabase import create_client, Client
from tqdm import tqdm

from unified_catalog import sync_atb_products_to_unified_catalog

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

load_dotenv()

BASE_URL = "https://www.atbmarket.com"
ECONOMY_URL = f"{BASE_URL}/catalog/economy"
SITEMAP_URL = f"{BASE_URL}/sitemap_catalog.xml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
                    "is_economy": is_economy,
                    "category_name": category_name,
                    "category_url": category_url,
                    "shop": "atb",
                })

    return products


ProductMap = Dict[str, Dict[str, Any]]


def merge_product(products_map: ProductMap, product: Dict[str, Any]) -> str:
    key: str = product["sku"] if product["sku"] else product["url"]
    if not key:
        return "skip"

    if key not in products_map:
        p = product.copy()
        p["_categories"] = {product["category_name"]}
        p["_category_urls"] = {product["category_url"]}
        products_map[key] = p
        return "new"

    existing = products_map[key]
    existing["_categories"].add(product["category_name"])
    existing["_category_urls"].add(product["category_url"])
    if product.get("is_economy"):
        existing["is_economy"] = True
    return "updated"


def scrape_category(
    session: cffi_requests.Session,
    category_url: str,
    category_name: str,
    is_economy: bool,
    products_map: ProductMap,
    pbar_outer: Optional[Any] = None,
) -> Tuple[int, int]:
    new_count = 0
    updated_count = 0
    page = 1
    last_page: Optional[int] = None

    pbar_pages = tqdm(
        total=None,
        desc=f"  ↳ сторінки",
        unit="стор",
        leave=False,
        colour="cyan",
        dynamic_ncols=True,
    )

    while True:
        url = f"{category_url}?page={page}" if page > 1 else category_url
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
        except Exception as e:
            tqdm.write(f"    [!] Помилка мережі на сторінці {page}: {e}")
            break

        if resp.status_code == 404:
            break
        if resp.status_code != 200:
            tqdm.write(f"    [!] HTTP {resp.status_code} на {url}")
            break

        if last_page is None:
            last_page = get_last_page(resp.text)
            pbar_pages.total = last_page if last_page > 1 else None
            pbar_pages.refresh()

        raw = extract_products_from_html(
            resp.text, url, category_name, category_url, is_economy
        )

        if not raw:
            tqdm.write(f"    [!] Сторінка {page}: товарів не знайдено, зупиняємось")
            break

        for p in raw:
            result = merge_product(products_map, p)
            if result == "new":
                new_count += 1
            elif result == "updated":
                updated_count += 1

        pbar_pages.update(1)
        pbar_pages.set_postfix(
            знайдено=len(raw),
            нових=new_count,
            оновлено=updated_count,
        )

        if pbar_outer is not None:
            pbar_outer.set_postfix(
                категорія=category_name[:25],
                нових=new_count,
                оновлено=updated_count,
                всього=len(products_map),
            )

        if last_page and page >= last_page:
            break

        page += 1
        time.sleep(DELAY_BETWEEN_PAGES)

    pbar_pages.close()
    return new_count, updated_count


def main():
    print("=" * 60)
    print("  ATB Market — повний парсер усіх категорій -> Supabase")
    print("=" * 60)

    session = make_session()
    products_map: ProductMap = {}

    tqdm.write(f"\n[КРОК 1] Парсимо категорію «Економія» (Ціна тижня)")
    tqdm.write(f"  URL: {ECONOMY_URL}")
    econ_new, econ_upd = scrape_category(
        session,
        ECONOMY_URL,
        "Економія / Ціна тижня",
        is_economy=True,
        products_map=products_map,
    )
    tqdm.write(f"  [OK] Нових: {econ_new}, оновлено: {econ_upd}")
    time.sleep(DELAY_BETWEEN_CATEGORIES)

    tqdm.write(f"\n[КРОК 2] Шукаємо всі категорії...")
    categories = fetch_categories_from_sitemap(session)
    if not categories:
        tqdm.write("  Sitemap не дав результатів, пробуємо HTML...")
        categories = fetch_categories_from_html(session)

    economy_slugs = {"economy", "ekonomiya"}
    categories = [
        (url, name)
        for url, name in categories
        if not any(s in url.lower() for s in economy_slugs)
    ]
    tqdm.write(f"  Категорій для парсингу: {len(categories)}")

    tqdm.write(f"\n[КРОК 3] Парсимо всі категорії...\n")
    with tqdm(
        total=len(categories),
        desc="Категорії",
        unit="кат",
        colour="green",
        dynamic_ncols=True,
    ) as pbar_cats:
        for cat_url, cat_name in categories:
            pbar_cats.set_description(f"Категорія: {cat_name[:30]}")
            new_c, upd_c = scrape_category(
                session,
                cat_url,
                cat_name,
                is_economy=False,
                products_map=products_map,
                pbar_outer=pbar_cats,
            )
            tqdm.write(
                f"  ✓ {cat_name}: +{new_c} нових, ~{upd_c} у нових категоріях "
                f"(всього в БД: {len(products_map)})"
            )
            pbar_cats.update(1)
            time.sleep(DELAY_BETWEEN_CATEGORIES)

    tqdm.write(f"\n[КРОК 4] Підготовка результатів...")
    all_products: List[Dict[str, Any]] = []
    for p in products_map.values():
        row = {k: v for k, v in p.items() if not k.startswith("_")}
        row["category_name"] = " | ".join(sorted(p["_categories"]))
        row["category_url"] = " | ".join(sorted(p["_category_urls"]))
        all_products.append(row)

    print(f"\n[КРОК 5] Збереження в Supabase...")
    init_database()
    supabase = get_supabase_client()
    batch_upsert_to_supabase(supabase, all_products)

    print(f"\n[КРОК 5.1] Синхронізація unified catalog для shopping agent...")
    catalog_stats = sync_atb_products_to_unified_catalog(supabase, all_products)
    for key, value in catalog_stats.items():
        print(f"  {key}: {value}")
    
    print(f"\n[КРОК 6] Збереження резервної копії в CSV...")
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(all_products)

    print(f"  [OK] Збережено в Supabase та {OUTPUT_CSV}")
    print(f"\n{'=' * 60}")
    print(f"  Готово! {len(all_products)} унікальних товарів")
    economy_count = sum(1 for p in all_products if p.get("is_economy"))
    multi_cat_count = sum(
        1 for p in products_map.values() if len(p["_categories"]) > 1
    )
    print(f"  З них «Ціна тижня»: {economy_count}")
    print(f"  Товарів у кількох категоріях: {multi_cat_count}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
