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
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

OUTPUT_CSV = "atb_full.csv"

CSV_FIELDS = [
    "sku", "name", "brand", "weight", "unit",
    "url", "current_price", "regular_price", "discount",
    "is_promo", "is_available", "is_economy",
    "category_name", "category_url", "shop", "image_url",
]

DELAY_BETWEEN_PAGES = 0.8
DELAY_BETWEEN_CATEGORIES = 1.5

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TABLE_NAME = "atb_products"
BATCH_SIZE = 1000


def init_database():
    """Skip database initialization - table must be created manually in Supabase SQL Editor"""
    print(f"[DB] Note: Table '{TABLE_NAME}' must be created manually in Supabase SQL Editor")
    print(f"[DB] See init_db.sql for the table creation script")


def get_supabase_client() -> Client:
    """Create and return Supabase client"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables must be set")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def batch_upsert_to_supabase(client: Client, products: List[Dict[str, Any]]):
    """Upsert products to Supabase in batches"""
    if not products:
        return
    
    total = len(products)
    for i in range(0, total, BATCH_SIZE):
        batch = products[i:i + BATCH_SIZE]
        try:
            client.table(TABLE_NAME).upsert(batch).execute()
            print(f"[DB] Upserted batch {i//BATCH_SIZE + 1}/{(total + BATCH_SIZE - 1)//BATCH_SIZE}: {len(batch)} items")
        except Exception as e:
            print(f"[DB] Error upserting batch: {e}")
            raise


def make_session() -> cffi_requests.Session:
    """Сесія curl_cffi з імітацією Chrome — обходить Cloudflare TLS fingerprint."""
    s = cffi_requests.Session(impersonate="chrome124")
    try:
        s.get(BASE_URL, headers=HEADERS, timeout=20)
    except Exception:
        pass
    time.sleep(1)
    return s


def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(m.group(0)) if m else None


def slug_to_name(slug: str) -> str:
    """Перетворює URL-слаг на читабельну назву."""
    name = re.sub(r"^\d+-", "", slug)
    return name.replace("-", " ").title()


def get_last_page(html: str) -> int:
    """Знаходить номер останньої сторінки з пагінації."""
    soup = BeautifulSoup(html, "html.parser")
    last = 1
    for a in soup.select("a.product-pagination__link"):
        href = a.get("href", "")
        m = re.search(r"[?&]page=(\d+)", href)
        if m:
            p = int(m.group(1))
            if p > last:
                last = p
    return last


def fetch_categories_from_sitemap(session: cffi_requests.Session) -> List[Tuple[str, str]]:
    categories: List[Tuple[str, str]] = []
    print(f"[sitemap] Завантажую {SITEMAP_URL} ...")
    try:
        resp = session.get(SITEMAP_URL, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            print(f"[sitemap] Помилка HTTP {resp.status_code}")
            return categories
        root = ET.fromstring(resp.text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [el.text.strip() for el in root.findall(".//sm:loc", ns) if el.text]
        for loc in locs:
            path = urlparse(loc).path
            if not re.match(r"^/catalog/[^/]+$", path):
                continue
            slug = path.rstrip("/").split("/")[-1]
            name = slug_to_name(slug)
            categories.append((loc, name))
        print(f"[sitemap] Знайдено {len(categories)} категорій")
    except Exception as e:
        print(f"[sitemap] Помилка парсингу: {e}")
    return categories


def fetch_categories_from_html(session: cffi_requests.Session) -> List[Tuple[str, str]]:
    categories: List[Tuple[str, str]] = []
    print(f"[html] Шукаю категорії на {BASE_URL}/catalog ...")
    try:
        resp = session.get(f"{BASE_URL}/catalog", headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            print(f"[html] Помилка HTTP {resp.status_code}")
            return categories
        soup = BeautifulSoup(resp.text, "html.parser")
        seen: Set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not re.match(r"^/catalog/[^/?#]+$", href):
                continue
            full_url = urljoin(BASE_URL, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            slug = href.rstrip("/").split("/")[-1]
            name = slug_to_name(slug)
            categories.append((full_url, name))
        print(f"[html] Знайдено {len(categories)} категорій")
    except Exception as e:
        print(f"[html] Помилка: {e}")
    return categories


def extract_json_blobs(html: str) -> List[Any]:
    soup = BeautifulSoup(html, "html.parser")
    blobs = []
    for script in soup.find_all("script"):
        txt = script.string if script.string is not None else script.get_text(strip=False)
        if not txt:
            continue
        t = txt.strip()
        if script.get("type") == "application/ld+json":
            try:
                blobs.append(json.loads(t))
                continue
            except Exception:
                pass
        if t.startswith("{") or t.startswith("["):
            try:
                blobs.append(json.loads(t))
                continue
            except Exception:
                pass
        markers = [
            "__NEXT_DATA__", "__NUXT__",
            "window.__INITIAL_STATE__", "window.__PRELOADED_STATE__",
            "window.__APOLLO_STATE__",
        ]
        if any(mk in t for mk in markers):
            start_candidates = [i for i in (t.find("{"), t.find("[")) if i != -1]
            if start_candidates:
                start = min(start_candidates)
                end = max(t.rfind("}"), t.rfind("]"))
                if end > start:
                    try:
                        blobs.append(json.loads(t[start: end + 1]))
                    except Exception:
                        pass
    return blobs


def iter_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from iter_dicts(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_dicts(item)


def looks_like_product(d: Dict[str, Any]) -> bool:
    keys = {k.lower() for k in d}
    has_name = any(k in keys for k in ("name", "title"))
    has_price = any(k in keys for k in ("price", "currentprice", "regularprice"))
    return has_name and has_price


def extract_products_from_html(
    html: str,
    page_url: str,
    category_name: str,
    category_url: str,
    is_economy: bool,
) -> List[Dict[str, Any]]:
    products: List[Dict[str, Any]] = []
    soup = BeautifulSoup(html, "html.parser")

    items: List[Any] = []
    for sel in ["article.catalog-item", "div.catalog-item", "li.catalog-item"]:
        items = soup.select(sel)
        if items:
            break

    for card in items:
        name = ""
        for s in [".catalog-item__title", "h3", "h2", ".product-title", ".product-name"]:
            el = card.select_one(s)
            if el:
                name = el.get_text(strip=True)
                break
        if not name:
            continue

        current_price: Optional[float] = None
        el_price = card.select_one("data.product-price__top")
        if el_price and el_price.get("value"):
            current_price = safe_float(el_price["value"])
        else:
            for s in [".catalog-item__price-action", ".price-sale",
                      ".catalog-item__price", "[class*='price']"]:
                el = card.select_one(s)
                if el:
                    current_price = safe_float(el.get_text(strip=True))
                    if current_price is not None:
                        break

        regular_price = current_price
        el_old = card.select_one("data.product-price__bottom")
        if el_old and el_old.get("value"):
            regular_price = safe_float(el_old["value"])
        else:
            el = card.select_one(
                "[class*='price-old'], [class*='old-price'], .catalog-item__price--old"
            )
            if el:
                rp = safe_float(el.get_text(strip=True))
                if rp is not None:
                    regular_price = rp

        # Extract product page URL (not wishlist or other links)
        product_link = (
            card.select_one(".catalog-item__title a[href]")
            or card.select_one("a.catalog-item__photo-link[href]")
            or card.find("a", href=lambda h: h and "/product/" in h)
        )
        url = urljoin(page_url, product_link["href"]) if product_link else ""

        cart = card.select_one(".b-addToCart")
        sku = ""
        brand = ""
        weight = ""
        unit = ""
        discount = ""
        if cart:
            sku = cart.get("data-productid", "")
            brand = cart.get("data-brand", "")
            weight = cart.get("data-weight", "")
            unit = cart.get("data-current-measure", "")
            discount = cart.get("data-discount", "")

        image_url = ""
        img_el = card.select_one("img.catalog-item__img") or card.select_one("picture img") or card.select_one("img")
        if img_el and img_el.get("src"):
            image_url = img_el["src"]

        if not sku and url:
            m = re.search(r"/product/(\d+)", url)
            if m:
                sku = m.group(1)

        card_classes = card.get("class", [])
        is_available = "catalog-item--not-available" not in card_classes

        is_promo = bool(
            regular_price and current_price and regular_price > current_price
        )

        products.append({
            "sku": sku,
            "name": name,
            "brand": brand,
            "weight": weight,
            "unit": unit,
            "url": url,
            "current_price": current_price,
            "regular_price": regular_price,
            "discount": discount,
            "is_promo": is_promo,
            "is_available": is_available,
            "is_economy": is_economy,
            "category_name": category_name,
            "category_url": category_url,
            "shop": "atb",
            "image_url": image_url,
        })

    if not products:
        for blob in extract_json_blobs(html):
            for d in iter_dicts(blob):
                if not isinstance(d, dict) or not looks_like_product(d):
                    continue
                name = d.get("name") or d.get("title") or ""
                if not name:
                    continue
                current_price = safe_float(d.get("price") or d.get("currentPrice"))
                regular_price = (
                    safe_float(d.get("oldPrice") or d.get("regularPrice"))
                    or current_price
                )
                url = d.get("url", "")
                if url.startswith("/"):
                    url = urljoin(page_url, url)
                is_promo = bool(
                    regular_price and current_price and regular_price > current_price
                )
                image_url = d.get("image") or d.get("picture") or ""
                if isinstance(image_url, list) and image_url:
                    image_url = image_url[0]
                elif isinstance(image_url, dict):
                    image_url = image_url.get("url", "") or image_url.get("src", "")
                products.append({
                    "sku": str(d.get("id") or d.get("sku") or ""),
                    "name": name,
                    "brand": str(d.get("brand", "")),
                    "weight": "",
                    "unit": "",
                    "url": url,
                    "current_price": current_price,
                    "regular_price": regular_price,
                    "discount": "",
                    "is_promo": is_promo,
                    "is_available": True,
                    "is_economy": is_economy,
                    "category_name": category_name,
                    "category_url": category_url,
                    "shop": "atb",
                    "image_url": str(image_url),
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
