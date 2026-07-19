from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from supabase import Client, create_client

from catalog_normalization import normalize_product_name, normalize_text
from shopping_agent.config import Settings


SEARCH_FIELDS = (
    "normalized_name",
)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes"}
    return bool(value)


def _clean_or_token(token: str) -> str:
    return (
        token.replace(",", " ")
        .replace("(", " ")
        .replace(")", " ")
        .replace("%", " ")
        .strip()
    )


class ProductRepository:
    def __init__(self, client: Client):
        self.client = client

    @classmethod
    def from_settings(cls, settings: Settings) -> "ProductRepository":
        url, key = settings.require_supabase()
        return cls(create_client(url, key))

    def search_products(
        self,
        query: str,
        limit: int = 20,
        only_available: bool = True,
        min_price: float | None = None,
        max_price: float | None = None,
        category: str | None = None,
        sort_by: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_query = normalize_product_name(query)
        tokens = [
            _clean_or_token(token)
            for token in normalized_query.split()
            if len(_clean_or_token(token)) > 1
        ][:6]

        request = self.client.table("shopping_products").select("*")
        if only_available:
            request = request.eq("is_available", True)

        if min_price is not None:
            request = request.gte("current_price", min_price)
        if max_price is not None:
            request = request.lte("current_price", max_price)
        if category:
            request = request.ilike("canonical_category_name", f"%{category}%")

        if tokens:
            conditions = []
            for token in tokens:
                for field in SEARCH_FIELDS:
                    conditions.append(f"{field}.ilike.%{token}%")
            request = request.or_(",".join(conditions))
        fetch_limit = 250
        response = request.limit(fetch_limit).execute()
        rows = [self._public_product(row) for row in response.data or []]
        ranked = self._rank(rows, normalized_query)
        
        # Consider all reasonable matches (score >= 0.5) for sorting, or fallback to top N
        top_matches = [r for r in ranked if r.get("score", 0) >= 0.5]
        if not top_matches:
            top_matches = ranked[:max(limit * 3, 20)]
        
        if sort_by == "price_asc":
            top_matches.sort(key=lambda row: row.get("current_price") or 10**9)
        elif sort_by == "price_desc":
            top_matches.sort(key=lambda row: row.get("current_price") or 0, reverse=True)
        elif sort_by == "discount":
            top_matches.sort(
                key=lambda row: (
                    -self._discount_percentage(row),
                    row.get("current_price") is None,
                    row.get("current_price") or 10**9,
                )
            )
            
        return top_matches[:limit]

    def get_promos(
        self, 
        query: str = "", 
        limit: int = 20, 
        offset: int = 0, 
        store_slug: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        category: str | None = None,
        sort_by: str | None = None,
    ) -> list[dict[str, Any]]:
        if query.strip():
            rows = self.search_products(
                query, 
                limit=200, 
                only_available=True,
                min_price=min_price,
                max_price=max_price,
                category=category,
            )
            rows = [row for row in rows if row["is_promo"] or row["is_economy"]]
            if store_slug:
                rows = [row for row in rows if row.get("store_slug") == store_slug]
        else:
            request = (
                self.client.table("shopping_products")
                .select("*")
                .eq("is_available", True)
                .or_("is_promo.eq.true,is_economy.eq.true")
            )
            if store_slug:
                request = request.eq("store_slug", store_slug)
            if min_price is not None:
                request = request.gte("current_price", min_price)
            if max_price is not None:
                request = request.lte("current_price", max_price)
            if category:
                request = request.ilike("canonical_category_name", f"%{category}%")
                
            response = request.limit(1000).execute()
            rows = [self._public_product(row) for row in response.data or []]

        if sort_by == "price_asc":
            rows.sort(key=lambda row: row.get("current_price") or 10**9)
        elif sort_by == "price_desc":
            rows.sort(key=lambda row: row.get("current_price") or 0, reverse=True)
        else:
            rows.sort(
                key=lambda row: (
                    -self._discount_percentage(row),
                    row.get("current_price") is None,
                    row.get("current_price") or 10**9,
                )
            )
        return rows[offset:offset+limit]

    def find_cheapest(self, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        if query.strip():
            rows = self.search_products(query, limit=150, only_available=True)
        else:
            response = (
                self.client.table("shopping_products")
                .select("*")
                .eq("is_available", True)
                .order("current_price")
                .limit(250)
                .execute()
            )
            rows = [self._public_product(row) for row in response.data or []]

        rows = [row for row in rows if row.get("current_price") is not None]
        rows.sort(
            key=lambda row: (
                row.get("price_per_unit") is None,
                row.get("price_per_unit") or row.get("current_price") or 10**9,
                row.get("current_price") or 10**9,
            )
        )
        return rows[:limit]

    def get_stats(self) -> dict[str, Any]:
        total = (
            self.client.table("shopping_products")
            .select("store_product_id", count="exact")
            .limit(1)
            .execute()
        )
        promos = (
            self.client.table("shopping_products")
            .select("store_product_id", count="exact")
            .or_("is_promo.eq.true,is_economy.eq.true")
            .limit(1)
            .execute()
        )
        return {
            "total_products": total.count,
            "promo_products": promos.count,
        }

    def get_stores(self) -> list[dict[str, Any]]:
        response = self.client.table("stores").select("id,name,slug").execute()
        return response.data or []

    def _rank(
        self,
        rows: list[dict[str, Any]],
        normalized_query: str,
    ) -> list[dict[str, Any]]:
        if not normalized_query:
            return rows

        query_tokens = set(normalized_query.split())
        for row in rows:
            haystack = normalize_text(
                " ".join(
                    str(row.get(field) or "")
                    for field in (
                        "name",
                        "brand",
                        "raw_category_name",
                        "canonical_category_name",
                    )
                )
            )
            row_tokens = set(haystack.split())
            overlap = len(query_tokens & row_tokens) / max(len(query_tokens), 1)
            name_ratio = SequenceMatcher(
                None,
                normalized_query,
                normalize_product_name(row.get("name")),
            ).ratio()
            
            # Penalize items with junk words if the query didn't ask for them
            junk_penalty = 0.0
            junk_words = [
                "згущен", "сирок", "морозиво", "напій", "печиво", "цукерки", 
                "десерт", "кефір", "гель", "мило", "шампунь", "крем", "маска", "піна"
            ]
            if not any(w in normalized_query for w in junk_words):
                row_name = normalize_text(row.get("name") or "")
                if any(w in row_name for w in junk_words):
                    junk_penalty = 0.4
                    
            row["score"] = round((overlap * 0.7) + (name_ratio * 0.3) - junk_penalty, 4)

        rows.sort(
            key=lambda row: (
                row.get("score") or 0,
                bool(row.get("is_promo") or row.get("is_economy")),
            ),
            reverse=True,
        )
        return rows

    def _public_product(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "store_product_id": row.get("store_product_id"),
            "canonical_product_id": row.get("canonical_product_id"),
            "store": row.get("store"),
            "store_slug": row.get("store_slug"),
            "store_sku": row.get("store_sku"),
            "name": row.get("name") or "",
            "brand": row.get("brand"),
            "current_price": _to_float(row.get("current_price")),
            "regular_price": _to_float(row.get("regular_price")),
            "discount": row.get("discount"),
            "is_promo": _to_bool(row.get("is_promo")),
            "is_economy": _to_bool(row.get("is_economy")),
            "is_available": _to_bool(row.get("is_available"), default=True),
            "raw_category_name": row.get("raw_category_name"),
            "canonical_category_name": row.get("canonical_category_name"),
            "normalized_weight": _to_float(row.get("normalized_weight")),
            "normalized_unit": row.get("normalized_unit"),
            "price_per_unit": _to_float(row.get("price_per_unit")),
            "url": row.get("url"),
            "image_url": row.get("image_url"),
            "score": _to_float(row.get("score")),
        }

    @staticmethod
    def _discount_percentage(row: dict[str, Any]) -> float:
        regular = _to_float(row.get("regular_price"))
        current = _to_float(row.get("current_price"))
        if regular and current and regular > current and regular > 0:
            return (regular - current) / regular * 100.0
            
        val = row.get("discount")
        if val and "%" in str(val):
            digits = "".join(ch for ch in str(val) if ch.isdigit())
            if digits:
                return float(digits)
                
        return 0.0

