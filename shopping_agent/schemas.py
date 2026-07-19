from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    limit: int = Field(default=12, ge=1, le=100)
    use_llm: bool = True


class ProductResult(BaseModel):
    store_product_id: int | None = None
    canonical_product_id: int | None = None
    store: str | None = None
    store_slug: str | None = None
    store_sku: str | None = None
    name: str
    brand: str | None = None
    current_price: float | None = None
    regular_price: float | None = None
    discount: str | None = None
    is_promo: bool = False
    is_economy: bool = False
    is_available: bool = True
    raw_category_name: str | None = None
    canonical_category_name: str | None = None
    normalized_weight: float | None = None
    normalized_unit: str | None = None
    price_per_unit: float | None = None
    url: str | None = None
    image_url: str | None = None
    score: float | None = None


class ChatResponse(BaseModel):
    answer: str
    intent: str = ""
    query: str = ""
    used_llm: bool
    products: list[ProductResult]
    meta: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    supabase_configured: bool
    llm_configured: bool
    model: str
