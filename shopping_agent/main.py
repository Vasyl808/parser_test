from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from shopping_agent.config import Settings
from shopping_agent.llm import GeminiClient
from shopping_agent.repository import ProductRepository
from shopping_agent.schemas import ChatRequest, ChatResponse, HealthResponse, ProductResult
from shopping_agent.service import ShoppingAgent
from shopping_agent.tts import TextToSpeech

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dependency singletons
# ---------------------------------------------------------------------------

@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()


@lru_cache
def get_repository() -> ProductRepository:
    return ProductRepository.from_settings(get_settings())


@lru_cache
def get_agent() -> ShoppingAgent:
    settings = get_settings()
    llm = None
    if settings.gemini_api_key:
        llm = GeminiClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            base_url=settings.gemini_base_url,
        )
    return ShoppingAgent(
        repository=get_repository(),
        llm=llm,
        default_limit=settings.agent_max_products,
    )


@lru_cache
def get_tts() -> TextToSpeech:
    settings = get_settings()
    return TextToSpeech(voice=settings.tts_voice, rate=settings.tts_rate)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

settings = get_settings()
app = FastAPI(
    title="Shopping Agent MVP",
    version="0.2.0",
    description="ATB-first shopping assistant API backed by Supabase, with voice support.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the static directory so voice_ui.html (and future assets) are served.
_static_dir = Path(__file__).resolve().parent / "static"
try:
    _static_dir.mkdir(exist_ok=True)
except OSError:
    pass # In Vercel serverless environment, filesystem is read-only

# Only mount if the directory actually exists (prevents crash on Vercel)
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ---------------------------------------------------------------------------
# Existing endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        supabase_configured=bool(settings.supabase_url and settings.supabase_key),
        llm_configured=bool(settings.gemini_api_key),
        model=settings.gemini_model,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    agent: ShoppingAgent = Depends(get_agent),
) -> ChatResponse:
    logger.info("POST /chat | message=%r | use_llm=%s", request.message, request.use_llm)
    result = await agent.chat(
        message=request.message,
        limit=request.limit,
        use_llm=request.use_llm,
    )
    logger.info(
        "POST /chat DONE | intent=%s | products=%d | used_llm=%s | error=%s",
        result.get("intent"), len(result.get("products", [])),
        result.get("used_llm"), result.get("meta", {}).get("error")
    )
    return ChatResponse(**result)


@app.get("/products/search", response_model=list[ProductResult])
def search_products(
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(default=20, ge=1, le=100),
    repository: ProductRepository = Depends(get_repository),
) -> list[ProductResult]:
    return [ProductResult(**row) for row in repository.search_products(q, limit=limit)]


@app.get("/products/promos", response_model=list[ProductResult])
def promo_products(
    q: str = Query(default="", max_length=500),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    store: str | None = Query(default=None, max_length=50),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    category: str | None = Query(default=None, max_length=100),
    sort_by: str | None = Query(default=None, max_length=20),
    repository: ProductRepository = Depends(get_repository),
) -> list[ProductResult]:
    return [ProductResult(**row) for row in repository.get_promos(
        q, 
        limit=limit, 
        offset=offset, 
        store_slug=store,
        min_price=min_price,
        max_price=max_price,
        category=category,
        sort_by=sort_by
    )]


@app.get("/products/cheapest", response_model=list[ProductResult])
def cheapest_products(
    q: str = Query(default="", max_length=500),
    limit: int = Query(default=20, ge=1, le=100),
    repository: ProductRepository = Depends(get_repository),
) -> list[ProductResult]:
    return [ProductResult(**row) for row in repository.find_cheapest(q, limit=limit)]


@app.get("/stats")
def stats(repository: ProductRepository = Depends(get_repository)):
    return repository.get_stats()


@app.get("/stores")
def list_stores(repository: ProductRepository = Depends(get_repository)):
    """List all available stores."""
    return repository.get_stores()


# ---------------------------------------------------------------------------
# Voice endpoints
# ---------------------------------------------------------------------------

class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str | None = None
    rate: str | None = None


@app.post("/voice/synthesize")
async def voice_synthesize(
    request: SynthesizeRequest,
    tts: TextToSpeech = Depends(get_tts),
) -> Response:
    """Convert text to speech. Returns MP3 audio bytes."""
    audio_bytes = await tts.synthesize(
        text=request.text,
        voice=request.voice,
        rate=request.rate,
    )
    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'inline; filename="speech.mp3"'},
    )


@app.get("/voice/voices")
def voice_voices():
    """List available Ukrainian TTS voices."""
    return TextToSpeech.list_voices()
