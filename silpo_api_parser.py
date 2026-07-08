# -*- coding: utf-8 -*-
"""
Парсер Silpo через JSON API sf-ecom-api.silpo.ua -> CSV.

Значно простіше й надійніше за HTML-версію (silpo_parser.py): не треба
парсити картки товарів через BeautifulSoup, і схоже, API не має такого
жорсткого bot-захисту, як сторінки сайту (curl_cffi лишив про всяк випадок).

Ідея:
  1. Список категорій — з головного меню сайту (ul.menu-categories), як і
     в HTML-версії. Публічного JSON-ендпоінта для категорій я не знайшов.
  2. Для кожної категорії йдемо в
     GET /v1/uk/branches/{branchId}/products?category=<slug>&includeChildCategories=true&...
     і гортаємо сторінками через limit/offset, поки offset < total.
     includeChildCategories=true means: одна категорія верхнього рівня =
     всі товари з усіх її підкатегорій одразу, без окремого обходу підкатегорій.
  3. "Ціна тижня" тепер НЕ окрема сторінка (як у ATБ/HTML-версії), а прапорець
     всередині кожного товару: is_economy = True, якщо в товару
     promotions містить {"id": "cinotyzhyky"}.
  4. Дедублікація за externalProductId (SKU) через set.

ВАЖЛИВІ ЗАСТЕРЕЖЕННЯ:
  - branchId = 00000000-0000-0000-0000-000000000000 — це, судячи з усього,
    "гостьова"/дефолтна філія (без обраної адреси доставки). Ціни можуть
    відрізнятися для конкретного магазину. Якщо потрібні ціни саме для
    вашого супермаркету — треба підставити реальний branchId (можна
    підглянути в DevTools → Network на сайті після вибору адреси доставки).
  - Це недокументований (reverse-engineered) API, може змінитися без
    попередження. Якщо колись отримаєте 403/429 — знадобиться додати
    затримки/ротацію User-Agent або повернутись до HTML-версії.
  - limit=100 нижче — мій вибір, я не перевіряв верхню межу, яку приймає
    сервер. Пагінація написана так, щоб коректно працювати з будь-яким
    реальним limit, який поверне сервер (reads data["limit"]/data["total"]).

Використання:
    python silpo_api_parser.py
"""
import io
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from dotenv import load_dotenv
from supabase import create_client, Client
from tqdm import tqdm

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Load environment variables from .env file if it exists
load_dotenv()

# ─── Налаштування ──────────────────────────────────────────────────────────────

BASE_URL = "https://silpo.ua"
BRANCH_ID = "00000000-0000-0000-0000-000000000000"  # дефолтна ("гостьова") філія
API_PRODUCTS_URL = f"https://sf-ecom-api.silpo.ua/v1/uk/branches/{BRANCH_ID}/products"

CINOTYZHYKY_PROMO_ID = "cinotyzhyky"  # аналог "Економія" в АТБ / is_economy

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
}

PAGE_SIZE = 100
BATCH_SIZE = 1000
TABLE_NAME = "silpo_products"

# Перші 14 полів 1-в-1 повторюють CSV_FIELDS з test_parser.py (АТБ) —
# для прямого мерджу. Решта — специфічні для Сільпо (тепер набагато
# точніші, бо беруться прямо з API, а не вгадуються з HTML).
CSV_FIELDS = [
    "sku", "name", "brand", "weight", "unit",
    "url", "current_price", "regular_price", "discount",
    "is_promo", "is_available", "is_economy",
    "category_name", "category_url",
    "bulk_price", "bulk_qty", "rating", "rating_count",
    "stock", "weighted", "section_slug", "promotions", "shop",
]

DELAY_BETWEEN_PAGES = 0.5
DELAY_BETWEEN_CATEGORIES = 1.0

# Supabase settings
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


# ─── Сесія ─────────────────────────────────────────────────────────────────────

def make_session() -> cffi_requests.Session:
    s = cffi_requests.Session(impersonate="chrome124")
    try:
        s.get(BASE_URL, headers=HEADERS, timeout=20)
    except Exception:
        pass
    time.sleep(1)
    return s


# ─── Утиліти ───────────────────────────────────────────────────────────────────

def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(m.group(0)) if m else None


def parse_weight_unit(text: str) -> Tuple[str, str]:
    """'345г' -> ('345', 'г'); '0,3кг' -> ('0.3', 'кг')"""
    if not text:
        return "", ""
    t = text.strip().replace(",", ".")
    m = re.match(r"([\d.]+)\s*(кг|г|л|мл|шт)", t, re.IGNORECASE)
    if m:
        return m.group(1), m.group(2).lower()
    return t, ""


def calc_discount_percent(current: Optional[float], old: Optional[float]) -> str:
    if not current or not old or old <= current:
        return ""
    return str(round((1 - current / old) * 100))


def slug_to_name(slug: str) -> str:
    name = re.sub(r"-\d+$", "", slug)
    return name.replace("-", " ").title()


# ─── Database Initialization ─────────────────────────────────────────────────────

def init_database():
    """Skip database initialization - table must be created manually in Supabase SQL Editor"""
    print(f"[DB] Note: Table '{TABLE_NAME}' must be created manually in Supabase SQL Editor")
    print(f"[DB] See init_db.sql for the table creation script")
    print(f"[DB] Skipping automatic initialization...")


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
            result = client.table(TABLE_NAME).upsert(batch).execute()
            print(f"[DB] Upserted batch {i//BATCH_SIZE + 1}/{(total + BATCH_SIZE - 1)//BATCH_SIZE}: {len(batch)} items")
        except Exception as e:
            print(f"[DB] Error upserting batch: {e}")
            raise


# ─── Пошук категорій (з HTML-меню — публічного JSON-ендпоінта не знайдено) ────

def fetch_categories_from_menu(session: cffi_requests.Session) -> List[Tuple[str, str, str]]:
    """
    Повертає список (slug, url, name), напр.
    ("m-iaso-4411", "https://silpo.ua/category/m-iaso-4411", "М'ясо").
    slug — те саме значення, яке підставляється в ?category=... в API.
    """
    categories: List[Tuple[str, str, str]] = []
    print(f"[menu] Завантажую {BASE_URL} ...")
    try:
        resp = session.get(BASE_URL, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            print(f"[menu] Помилка HTTP {resp.status_code}")
            return categories
        soup = BeautifulSoup(resp.text, "html.parser")
        seen: Set[str] = set()
        for a in soup.select("a.menu-categories__link[href]"):
            href = a["href"]
            if not href.startswith("/category/"):
                continue
            full_url = urljoin(BASE_URL, href)
            slug = urlparse(full_url).path.rstrip("/").split("/")[-1]
            if slug in seen:
                continue
            seen.add(slug)

            name = ""
            for node in a.contents:
                if isinstance(node, str) and node.strip():
                    name = node.strip()
                    break
            if not name:
                name = slug_to_name(slug)

            categories.append((slug, full_url, name))
        print(f"[menu] Знайдено {len(categories)} категорій")
    except Exception as e:
        print(f"[menu] Помилка парсингу: {e}")
    return categories


# ─── Робота з API товарів ───────────────────────────────────────────────────────

def fetch_products_page(
    session: cffi_requests.Session,
    category_slug: str,
    limit: int,
    offset: int,
) -> Dict[str, Any]:
    params = {
        "limit": limit,
        "offset": offset,
        "deliveryType": "DeliveryHome",
        "category": category_slug,
        "includeChildCategories": "true",
        "sortBy": "popularity",
        "sortDirection": "desc",
        "inStock": "false",
    }
    resp = session.get(API_PRODUCTS_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def map_item_to_row(item: Dict[str, Any], category_name: str, category_url: str) -> Dict[str, Any]:
    current_price = safe_float(item.get("displayPrice"))
    old_price = safe_float(item.get("displayOldPrice"))
    regular_price = old_price if old_price is not None else current_price

    weight, unit = parse_weight_unit(item.get("displayRatio", ""))

    special_prices = item.get("specialPrices") or []
    bulk_price = safe_float(special_prices[0].get("price")) if special_prices else None
    bulk_qty = special_prices[0].get("count") if special_prices else None

    promotions = item.get("promotions") or []
    promo_ids = [p.get("id", "") for p in promotions if p.get("id")]
    is_economy = CINOTYZHYKY_PROMO_ID in promo_ids

    stock = item.get("stock")
    is_available = True if stock is None else (stock > 0)

    slug = item.get("slug", "")
    url = urljoin(BASE_URL, f"/product/{slug}") if slug else ""

    sku = item.get("externalProductId")
    sku = str(sku) if sku is not None else ""

    is_promo = bool(regular_price and current_price and regular_price > current_price)

    return {
        "sku": sku,
        "name": item.get("title", ""),
        "brand": item.get("brandTitle", "") or "",
        "weight": weight,
        "unit": unit,
        "url": url,
        "current_price": current_price,
        "regular_price": regular_price,
        "discount": calc_discount_percent(current_price, regular_price),
        "is_promo": is_promo,
        "is_available": is_available,
        "is_economy": is_economy,
        "category_name": category_name,
        "category_url": category_url,
        "bulk_price": bulk_price,
        "bulk_qty": bulk_qty,
        "rating": item.get("guestProductRating"),
        "rating_count": item.get("guestProductRatingCount"),
        "stock": stock,
        "weighted": item.get("weighted", False),
        "section_slug": item.get("sectionSlug", ""),
        "promotions": ",".join(promo_ids),
        "shop": "silpo",
    }


def scrape_category_api(
    session: cffi_requests.Session,
    category_slug: str,
    category_name: str,
    category_url: str,
    seen_skus: Set[str],
    pbar_outer: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    new_products: List[Dict[str, Any]] = []
    offset = 0
    total: Optional[int] = None

    pbar_pages = tqdm(
        total=None,
        desc="  ↳ сторінки",
        unit="стор",
        leave=False,
        colour="cyan",
        dynamic_ncols=True,
    )

    while True:
        try:
            data = fetch_products_page(session, category_slug, PAGE_SIZE, offset)
        except Exception as e:
            tqdm.write(f"    [!] Помилка запиту (offset={offset}): {e}")
            break

        if total is None:
            total = data.get("total", 0) or 0
            actual_limit = data.get("limit") or PAGE_SIZE
            pbar_pages.total = max(1, -(-total // actual_limit)) if total else None
            pbar_pages.refresh()

        items = data.get("items") or []
        if not items:
            break

        added = 0
        for item in items:
            row = map_item_to_row(item, category_name, category_url)
            key = row["sku"] if row["sku"] else row["url"]
            if key and key in seen_skus:
                continue  # дублікат (може повторитись між підкатегоріями)
            seen_skus.add(key)
            new_products.append(row)
            added += 1

        pbar_pages.update(1)
        pbar_pages.set_postfix(
            знайдено=len(items),
            нових=added,
            унікальних=len(seen_skus),
        )
        if pbar_outer is not None:
            pbar_outer.set_postfix(
                категорія=category_name[:25],
                нових=len(new_products),
                унікальних=len(seen_skus),
            )

        offset += len(items)
        if total and offset >= total:
            break
        if len(items) < PAGE_SIZE:
            # сервер повернув менше, ніж просили — вважаємо, що це остання сторінка
            break

        time.sleep(DELAY_BETWEEN_PAGES)

    pbar_pages.close()
    return new_products


# ─── Головна функція ───────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Silpo API — повний парсер усіх категорій")
    print("=" * 60)

    session = make_session()

    seen_skus: Set[str] = set()
    all_products: List[Dict[str, Any]] = []

    print(f"\n[КРОК 1] Шукаємо всі категорії...")
    categories = fetch_categories_from_menu(session)
    print(f"  Категорій для парсингу: {len(categories)}")

    print(f"\n[КРОК 2] Парсимо всі категорії через API...\n")
    with tqdm(
        total=len(categories),
        desc="Категорії",
        unit="кат",
        colour="green",
        dynamic_ncols=True,
    ) as pbar_cats:
        for slug, cat_url, cat_name in categories:
            pbar_cats.set_description(f"Категорія: {cat_name[:30]}")
            cat_products = scrape_category_api(
                session,
                slug,
                cat_name,
                cat_url,
                seen_skus=seen_skus,
                pbar_outer=pbar_cats,
            )
            all_products.extend(cat_products)
            tqdm.write(
                f"  ✓ {cat_name}: +{len(cat_products)} нових "
                f"(загалом: {len(all_products)})"
            )
            pbar_cats.update(1)
            time.sleep(DELAY_BETWEEN_CATEGORIES)

    print(f"\n[КРОК 3] Ініціалізація бази даних...")
    init_database()
    
    print(f"\n[КРОК 4] Підключення до Supabase...")
    supabase = get_supabase_client()
    
    print(f"\n[КРОК 5] Збереження даних в Supabase...")
    print(f"  Всього унікальних товарів: {len(all_products)}")
    
    batch_upsert_to_supabase(supabase, all_products)
    
    print(f"  [OK] Дані успішно збережено в Supabase")
    print(f"\n{'=' * 60}")
    print(f"  Готово! {len(all_products)} унікальних товарів")
    economy_count = sum(1 for p in all_products if p.get("is_economy"))
    print(f"  З них «Цінотижки»: {economy_count}")
    print(f"{'=' * 60}\n")

    print("Перші 5 товарів:")
    for p in all_products[:5]:
        mark = " [ЦІНА ТИЖНЯ]" if p.get("is_economy") else ""
        print(
            f"  [{p['sku']}] {p['name']}{mark} - "
            f"{p['current_price']} грн (кат: {p['category_name']})"
        )


if __name__ == "__main__":
    main()
