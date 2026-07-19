from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


def _int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _origins_from_env(value: str | None) -> list[str]:
    if not value:
        return ["*"]
    origins = [origin.strip() for origin in value.split(",") if origin.strip()]
    return origins or ["*"]


@dataclass(frozen=True)
class Settings:
    supabase_url: str | None
    supabase_key: str | None
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    agent_max_products: int = 100
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    tts_voice: str = "uk-UA-PolinaNeural"
    tts_rate: str = "+0%"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_key=os.getenv("SUPABASE_KEY"),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
            gemini_base_url=os.getenv(
                "GEMINI_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta",
            ),
            agent_max_products=_int_from_env("AGENT_MAX_PRODUCTS", 100),
            cors_origins=_origins_from_env(os.getenv("CORS_ORIGINS")),
            tts_voice=os.getenv("TTS_VOICE", "uk-UA-PolinaNeural"),
            tts_rate=os.getenv("TTS_RATE", "+0%"),
        )

    def require_supabase(self) -> tuple[str, str]:
        if not self.supabase_url or not self.supabase_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured")
        return self.supabase_url, self.supabase_key

