from __future__ import annotations

from typing import Any

import httpx


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 30.0,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    async def generate(self, system_instruction: str, prompt: str) -> str:
        payload = {
            "model": self.model,
            "system_instruction": system_instruction,
            "input": prompt,
            "generation_config": {
                "temperature": 0.2,
                "thinking_level": "low",
            },
        }
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(self.base_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        text = data.get("output_text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        extracted = self._extract_text_from_steps(data)
        if extracted:
            return extracted

        raise RuntimeError("Gemini response did not contain text output")

    @staticmethod
    def _extract_text_from_steps(data: dict[str, Any]) -> str:
        chunks: list[str] = []
        for step in data.get("steps") or []:
            for content in step.get("content") or []:
                if content.get("type") == "text" and content.get("text"):
                    chunks.append(str(content["text"]))
        return "\n".join(chunks).strip()
