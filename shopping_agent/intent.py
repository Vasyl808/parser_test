from __future__ import annotations

from catalog_normalization import normalize_text


PROMO_WORDS = {
    "акція",
    "акції",
    "акційні",
    "знижка",
    "знижки",
    "знижкою",
    "промо",
    "економія",
    "економ",
}

PROMO_PREFIXES = ("акц", "зниж", "промо", "економ")

CHEAP_WORDS = {
    "дешево",
    "дешеве",
    "дешевий",
    "дешевші",
    "дешевше",
    "найдешевше",
    "найдешевший",
    "мінімальна",
    "мінімальну",
    "ціна",
    "ціною",
}

CHEAP_PREFIXES = ("дешев", "найдешев", "мінімаль", "вигідн")

AVAILABILITY_WORDS = {
    "є",
    "наявності",
    "наявний",
    "доступний",
}

QUERY_STOP_WORDS = PROMO_WORDS | CHEAP_WORDS | AVAILABILITY_WORDS | {
    "де",
    "що",
    "шо",
    "які",
    "який",
    "яка",
    "чи",
    "мені",
    "покажи",
    "показати",
    "знайди",
    "знайти",
    "в",
    "у",
    "на",
    "по",
    "для",
    "атб",
    "atb",
    "сільпо",
    "silpo",
    "товар",
    "товари",
    "продукт",
    "продукти",
    "купити",
    "покупки",
    "можна",
    "зараз",
}


def _has_prefix(words: set[str], prefixes: tuple[str, ...]) -> bool:
    return any(word.startswith(prefix) for word in words for prefix in prefixes)


def _is_query_stop_word(word: str) -> bool:
    return (
        word in QUERY_STOP_WORDS
        or any(word.startswith(prefix) for prefix in PROMO_PREFIXES)
        or any(word.startswith(prefix) for prefix in CHEAP_PREFIXES)
    )


def detect_intent(message: str) -> str:
    normalized = normalize_text(message)
    words = set(normalized.split())
    if "ціна тижня" in normalized:
        return "promos"
    if words & PROMO_WORDS or _has_prefix(words, PROMO_PREFIXES):
        return "promos"
    if words & CHEAP_WORDS or _has_prefix(words, CHEAP_PREFIXES):
        return "cheapest"
    if words & AVAILABILITY_WORDS:
        return "availability"
    return "search"


def extract_product_query(message: str) -> str:
    words = normalize_text(message).split()
    useful = [word for word in words if not _is_query_stop_word(word) and len(word) > 1]
    if useful:
        return " ".join(useful)
    return ""
