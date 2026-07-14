"""Normalization helpers for the shopping catalog.

The parser stores raw shop data unchanged, while the unified catalog stores a
normalized projection used for search, matching, and price-per-unit sorting.
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Optional


_SPACES_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^0-9a-zа-щьюяєіїґ%.,+\-\s']", re.IGNORECASE)
_WEIGHT_RE = re.compile(
    r"(?P<value>\d+(?:[,.]\d+)?)\s*(?P<unit>кг|kg|г|g|гр|л|l|мл|ml|шт|pcs|pc)\b",
    re.IGNORECASE,
)

UNIT_ALIASES = {
    "кг": "kg",
    "kg": "kg",
    "г": "g",
    "гр": "g",
    "g": "g",
    "л": "l",
    "l": "l",
    "мл": "ml",
    "ml": "ml",
    "шт": "pcs",
    "pc": "pcs",
    "pcs": "pcs",
}

BASE_UNITS = {
    "kg": ("kg", Decimal("1")),
    "g": ("kg", Decimal("0.001")),
    "l": ("l", Decimal("1")),
    "ml": ("l", Decimal("0.001")),
    "pcs": ("pcs", Decimal("1")),
}

PRODUCT_NOISE_WORDS = {
    "акція",
    "знижка",
    "ціна",
    "тижня",
    "упаковка",
    "паковання",
}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = text.replace("’", "'").replace("`", "'").replace("ʼ", "'")
    text = text.replace("ё", "е")
    text = _NON_WORD_RE.sub(" ", text)
    text = text.replace(",", ".")
    text = _SPACES_RE.sub(" ", text)
    return text.strip()


def normalize_product_name(name: Any) -> str:
    text = normalize_text(name)
    text = _WEIGHT_RE.sub(" ", text)
    words = [word for word in text.split() if word not in PRODUCT_NOISE_WORDS]
    return " ".join(words)


def normalize_brand(brand: Any) -> str:
    return normalize_text(brand)


def normalize_unit(unit: Any) -> str:
    normalized = normalize_text(unit)
    return UNIT_ALIASES.get(normalized, normalized)


def _decimal_from_any(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(" ", "").replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def extract_weight_from_name(name: Any) -> tuple[Optional[Decimal], str]:
    text = normalize_text(name)
    match = _WEIGHT_RE.search(text)
    if not match:
        return None, ""
    return _decimal_from_any(match.group("value")), normalize_unit(match.group("unit"))


def normalize_weight(
    weight: Any,
    unit: Any,
    fallback_name: Any = "",
) -> tuple[Optional[Decimal], str]:
    raw_weight = _decimal_from_any(weight)
    raw_unit = normalize_unit(unit)

    if raw_weight is None or not raw_unit:
        extracted_weight, extracted_unit = extract_weight_from_name(fallback_name)
        raw_weight = raw_weight if raw_weight is not None else extracted_weight
        raw_unit = raw_unit or extracted_unit

    if raw_weight is None or not raw_unit:
        return None, ""

    base = BASE_UNITS.get(raw_unit)
    if not base:
        return raw_weight, raw_unit

    base_unit, multiplier = base
    normalized_weight = (raw_weight * multiplier).quantize(
        Decimal("0.0001"),
        rounding=ROUND_HALF_UP,
    )
    return normalized_weight, base_unit


def calculate_price_per_unit(
    current_price: Any,
    normalized_weight: Optional[Decimal],
) -> Optional[Decimal]:
    price = _decimal_from_any(current_price)
    if price is None or normalized_weight is None or normalized_weight <= 0:
        return None
    return (price / normalized_weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def split_category_names(category_name: Any) -> list[str]:
    if not category_name:
        return []
    parts = [part.strip() for part in str(category_name).split("|")]
    return [part for part in parts if part]


def choose_primary_category(category_names: Iterable[str]) -> str:
    names = list(category_names)
    if not names:
        return "Без категорії"

    for name in names:
        normalized = normalize_text(name)
        if "економ" not in normalized and "ціна тижня" not in normalized:
            return name
    return names[0]


def stable_store_sku(row: dict[str, Any]) -> str:
    sku = str(row.get("sku") or "").strip()
    if sku:
        return sku

    fallback = "|".join(
        str(row.get(key) or "")
        for key in ("url", "name", "brand", "weight", "unit")
    )
    digest = hashlib.sha1(fallback.encode("utf-8")).hexdigest()[:16]
    return f"generated:{digest}"


def make_canonical_key(
    category_id: Any,
    normalized_brand: str,
    normalized_name: str,
    normalized_weight: Optional[Decimal],
    normalized_unit: str,
) -> str:
    weight_part = str(normalized_weight or "")
    raw = "|".join(
        [
            str(category_id or ""),
            normalized_brand or "",
            normalized_name or "",
            weight_part,
            normalized_unit or "",
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()
