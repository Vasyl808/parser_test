"""Text-to-Speech wrapper around the edge-tts library.

edge-tts is a lightweight HTTP client that calls Microsoft's Edge TTS cloud
service.  It downloads no models and needs no API keys — the server only
proxies the request and streams the resulting MP3 back to the caller.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

import edge_tts

# Ukrainian voices provided by Microsoft Edge TTS.
UKRAINIAN_VOICES: list[dict[str, str]] = [
    {
        "short_name": "uk-UA-PolinaNeural",
        "gender": "Female",
        "display_name": "Поліна",
    },
    {
        "short_name": "uk-UA-OstapNeural",
        "gender": "Male",
        "display_name": "Остап",
    },
]

DEFAULT_VOICE = "uk-UA-PolinaNeural"
DEFAULT_RATE = "+0%"


@dataclass
class TextToSpeech:
    """Thin async wrapper around *edge-tts*."""

    voice: str = DEFAULT_VOICE
    rate: str = DEFAULT_RATE

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        rate: str | None = None,
    ) -> bytes:
        """Convert *text* to MP3 bytes using Microsoft Edge TTS.

        Parameters
        ----------
        text:
            The Ukrainian (or any) text to speak.
        voice:
            Override the default voice for this single call.
        rate:
            Speech rate adjustment, e.g. ``"+10%"`` or ``"-20%"``.

        Returns
        -------
        bytes
            Raw MP3 audio.
        """
        effective_voice = voice or self.voice
        effective_rate = rate or self.rate

        communicate = edge_tts.Communicate(
            text,
            voice=effective_voice,
            rate=effective_rate,
        )

        buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buffer.write(chunk["data"])

        return buffer.getvalue()

    @staticmethod
    def list_voices() -> list[dict[str, str]]:
        """Return the hardcoded list of Ukrainian voices."""
        return list(UKRAINIAN_VOICES)
