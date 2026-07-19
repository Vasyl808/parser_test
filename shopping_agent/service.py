from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

from shopping_agent.llm import GeminiClient
from shopping_agent.repository import ProductRepository


def _discount_number(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(str(val).replace("%", "").strip())
    except (ValueError, TypeError):
        return 0.0


SYSTEM_INSTRUCTION = """
Ти AI помічник з покупок (АТБ та Сільпо). Завжди використовуй інструмент search_products — ніколи не вигадуй товари.

ЛІМІТИ (визначай динамічно):
- Один товар → limit=3-5
- Товар з різноманіттям (морозиво, сир, вода) → limit=7-10
- Інгредієнт рецепту → limit=2-3, але виклич search_products для КОЖНОГО інгредієнту окремо
- Якщо >3 страви одночасно — обмежся першими 3-ма і скажи про це

СОРТУВАННЯ:
- "дешеве/найдешевше/вигідне" → sort_by="price_asc"
- "акція/знижка/промо" → only_promos=true, sort_by="discount"
- "дороге/преміум" → sort_by="price_desc"

ВІДПОВІДЬ: коротко, українською, без маркдауну, зі цінами та назвами магазинів.
""".strip()

TOOLS = [{
    "function_declarations": [
        {
            "name": "search_products",
            "description": "Пошук товарів в базі даних магазинів АТБ та Сільпо. Можна викликати кілька разів для різних інгредієнтів рецепту.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "Пошуковий запит — назва товару або інгредієнту (наприклад 'молоко', 'яйця', 'буряк')"
                    },
                    "min_price": {
                        "type": "NUMBER",
                        "description": "Мінімальна ціна у гривнях (опціонально)"
                    },
                    "max_price": {
                        "type": "NUMBER",
                        "description": "Максимальна ціна у гривнях (опціонально)"
                    },
                    "only_promos": {
                        "type": "BOOLEAN",
                        "description": "Якщо true — повертає тільки акційні товари зі знижками"
                    },
                    "sort_by": {
                        "type": "STRING",
                        "description": "Метод сортування: 'price_asc' (від дешевих), 'price_desc' (від дорогих), 'discount' (найбільша знижка)"
                    },
                    "limit": {
                        "type": "INTEGER",
                        "description": "Кількість товарів. Визначай динамічно: 2-3 для інгредієнту рецепту, 3-5 для простого запиту, 7-10 для запиту з різноманіттям (морозиво, сир тощо)"
                    }
                },
                "required": ["query"]
            }
        }
    ]
}]

# Hard cap to prevent runaway token usage
MAX_PRODUCTS_TOTAL = 50
MAX_AGENT_TURNS = 12  # Enough for a recipe with ~10 ingredients


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
        if not use_llm or not self.llm:
            return {
                "answer": "Режим без LLM більше не підтримується.",
                "used_llm": False,
                "products": [],
                "meta": {}
            }

        messages = [{"role": "user", "parts": [{"text": message}]}]
        all_products: list[dict[str, Any]] = []
        llm_error = None

        try:
            for turn in range(MAX_AGENT_TURNS):
                logger.info("[Agent turn %d] Sending %d messages to Gemini", turn + 1, len(messages))
                response = await self.llm.chat_with_tools(SYSTEM_INSTRUCTION, messages, TOOLS)

                if response["type"] == "function_calls":
                    calls = response["calls"]
                    logger.info("[Agent turn %d] Got %d function call(s)", turn + 1, len(calls))
                    
                    # Build model message exactly as returned to preserve signatures/thoughts
                    if "model_content" in response:
                        messages.append(response["model_content"])
                    else:
                        model_parts = []
                        for call in calls:
                            model_parts.append({
                                "functionCall": call.get("raw_call", {"name": call["name"], "args": call["args"]})
                            })
                        messages.append({"role": "model", "parts": model_parts})

                    # Execute each call and collect results
                    func_response_parts = []
                    for call in calls:
                        if call["name"] == "search_products":
                            logger.info("[Agent] Executing search_products(%s)", call["args"])
                            rows = self._execute_search(call["args"])
                            logger.info("[Agent] search_products returned %d rows", len(rows))
                            all_products.extend(rows)
                            
                            simplified = [self._simplify_product(r) for r in rows]
                            func_response_parts.append({
                                "functionResponse": {
                                    "name": call["name"],
                                    "response": {
                                        "name": call["name"],
                                        "content": simplified
                                    }
                                }
                            })

                    messages.append({"role": "function", "parts": func_response_parts})

                    # Safety: stop if we've accumulated too many products
                    if len(all_products) >= MAX_PRODUCTS_TOTAL:
                        logger.warning("[Agent] Hit MAX_PRODUCTS_TOTAL=%d, breaking loop", MAX_PRODUCTS_TOTAL)
                        break

                elif response["type"] == "text":
                    logger.info("[Agent turn %d] Got final text answer (%d chars), %d products total", turn + 1, len(response['text']), len(all_products))
                    # Deduplicate products by store_product_id
                    seen = set()
                    unique_products = []
                    for p in all_products:
                        pid = p.get("store_product_id")
                        if pid and pid not in seen:
                            seen.add(pid)
                            unique_products.append(p)
                        elif not pid:
                            unique_products.append(p)

                    return {
                        "answer": response["text"],
                        "intent": "react_agent",
                        "query": message,
                        "used_llm": True,
                        "products": unique_products,
                        "meta": {
                            "product_count": len(unique_products),
                            "agent_turns": turn + 1,
                        }
                    }
        except Exception as exc:
            llm_error = str(exc)
            logger.error("[Agent] Error: %s", llm_error, exc_info=True)

        return {
            "answer": "Вибачте, виникла помилка під час пошуку. Спробуйте ще раз.",
            "intent": "error",
            "query": message,
            "used_llm": True,
            "products": all_products,
            "meta": {"error": llm_error}
        }

    def _execute_search(self, args: dict) -> list[dict[str, Any]]:
        query = args.get("query", "")
        only_promos = args.get("only_promos", False)
        min_price = args.get("min_price")
        max_price = args.get("max_price")
        sort_by = args.get("sort_by")
        func_limit = args.get("limit", 5)

        if only_promos:
            return self.repository.get_promos(
                query=query,
                limit=func_limit,
                min_price=min_price,
                max_price=max_price,
                sort_by=sort_by,
            )
        
        return self.repository.search_products(
            query=query,
            limit=func_limit,
            min_price=min_price,
            max_price=max_price,
            only_available=True,
            sort_by=sort_by,
        )

    def _simplify_product(self, product: dict) -> dict:
        """Compact representation sent to LLM context to save tokens."""
        return {
            "name": product.get("name"),
            "store": product.get("store"),
            "current_price": product.get("current_price"),
            "regular_price": product.get("regular_price"),
            "discount": product.get("discount"),
            "is_promo": product.get("is_promo"),
            "price_per_unit": product.get("price_per_unit"),
            "normalized_unit": product.get("normalized_unit"),
        }
