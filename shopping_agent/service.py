from __future__ import annotations

import json
from typing import Any

from shopping_agent.intent import detect_intent, extract_product_query
from shopping_agent.llm import GeminiClient
from shopping_agent.repository import ProductRepository


SYSTEM_INSTRUCTION = """
Ти помічник з покупок для українського користувача.
Відповідай українською, коротко, дружньо і практично.
НЕ ВИКОРИСТОВУЙ маркдаун (ніяких зірочок ** чи маркерів списку *). Пиши простим суцільним текстом. Це важливо для коректного озвучення!
Використовуй тільки товари з переданого JSON-контексту.
Завжди вказуй назву магазину (АТБ, Сільпо) поряд з кожним товаром, щоб користувач знав де купити.
Не вигадуй ціни, магазини, знижки або наявність.
Якщо даних недостатньо, прямо скажи що не бачиш цього в базі.
""".strip()


class ShoppingAgent:
    def __init__(
        self,
        repository: ProductRepository,
        llm: GeminiClient | None = None,
        default_limit: int = 100,
    ):
        self.repository = repository
        self.llm = llm
        self.default_limit = default_limit

    async def chat(
        self,
        message: str,
        limit: int | None = None,
        use_llm: bool = True,
    ) -> dict[str, Any]:
        limit = limit or self.default_limit
        intent = detect_intent(message)
        query = extract_product_query(message)
        products = self._retrieve_products(intent, query, limit)

        used_llm = False
        answer = ""
        llm_error: str | None = None

        if use_llm and self.llm and products:
            try:
                answer = await self.llm.generate(
                    SYSTEM_INSTRUCTION,
                    self._build_prompt(message, intent, query, products),
                )
                used_llm = True
            except Exception as exc:
                llm_error = str(exc)

        if not answer:
            answer = self._fallback_answer(intent, query, products)

        meta: dict[str, Any] = {
            "product_count": len(products),
            "llm_error": llm_error,
        }
        return {
            "answer": answer,
            "intent": intent,
            "query": query,
            "used_llm": used_llm,
            "products": products,
            "meta": meta,
        }

    def _retrieve_products(
        self,
        intent: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if intent == "promos":
            return self.repository.get_promos(query=query, limit=limit)
        if intent == "cheapest":
            return self.repository.find_cheapest(query=query, limit=limit)
        return self.repository.search_products(query=query, limit=limit)

    def _build_prompt(
        self,
        message: str,
        intent: str,
        query: str,
        products: list[dict[str, Any]],
    ) -> str:
        context = [
            {
                "store": product.get("store"),
                "sku": product.get("store_sku"),
                "name": product.get("name"),
                "brand": product.get("brand"),
                "current_price": product.get("current_price"),
                "regular_price": product.get("regular_price"),
                "discount": product.get("discount"),
                "is_promo": product.get("is_promo"),
                "is_economy": product.get("is_economy"),
                "is_available": product.get("is_available"),
                "category": product.get("canonical_category_name")
                or product.get("raw_category_name"),
                "normalized_weight": product.get("normalized_weight"),
                "normalized_unit": product.get("normalized_unit"),
                "price_per_unit": product.get("price_per_unit"),
                "url": product.get("url"),
            }
            for product in products
        ]
        return json.dumps(
            {
                "user_question": message,
                "detected_intent": intent,
                "search_query": query,
                "products": context,
                "answer_rules": [
                    "Use only products from products.",
                    "Mention exact prices for recommendations.",
                    "If price_per_unit exists, use it for fair comparison.",
                    "Prefer available promo/economy products when relevant.",
                ],
            },
            ensure_ascii=False,
            default=str,
        )

    def _fallback_answer(
        self,
        intent: str,
        query: str,
        products: list[dict[str, Any]],
    ) -> str:
        if not products:
            if query:
                return f"Не знайшов актуальних товарів по запиту «{query}»."
            return "Не знайшов актуальних товарів для цього запиту."

        if intent == "promos":
            title = "🔥 Акційні позиції"
        elif intent == "cheapest":
            title = "💰 Найдешевші позиції"
        else:
            title = "🛒 Ось що знайшов"

        # Group by store
        by_store: dict[str, list[dict[str, Any]]] = {}
        for product in products[: self.default_limit]:
            store = product.get("store") or "Магазин"
            by_store.setdefault(store, []).append(product)

        lines = [f"{title}:\n"]
        idx = 1
        for store_name, store_products in by_store.items():
            store_emoji = "🏪" if store_name == "ATB" else "🟢" if store_name == "Silpo" else "🛍️"
            lines.append(f"{store_emoji} {store_name}:")
            for product in store_products:
                lines.append(self._format_product(product, idx))
                idx += 1
            lines.append("")  # blank line between stores
        return "\n".join(lines).rstrip()

    def _format_product(self, product: dict[str, Any], index: int = 0) -> str:
        name = product.get("name") or "Без назви"
        price = product.get("current_price")
        regular = product.get("regular_price")
        discount = product.get("discount")
        ppu = product.get("price_per_unit")
        unit_raw = product.get("normalized_unit")
        is_economy = product.get("is_economy")

        # Header line
        prefix = f"{index}. " if index else "• "
        line = f"{prefix}{name}"

        # Price line
        price_parts = []
        if price is not None:
            price_parts.append(f"   💵 {price:.2f} грн")
            if regular and regular != price:
                price_parts[0] += f"  (було {regular:.2f} грн)"

        # Tags line
        tags = []
        if discount:
            tags.append(f"🏷️ -{discount}%")
        if is_economy:
            tags.append("⭐ Ціна тижня")
        if ppu and unit_raw:
            unit_label = "кг" if unit_raw == "kg" else "л" if unit_raw == "l" else "шт"
            tags.append(f"📦 {ppu:.2f} грн/{unit_label}")

        result = line
        if price_parts:
            result += "\n" + "\n".join(price_parts)
        if tags:
            result += "\n   " + "  ".join(tags)
        return result

