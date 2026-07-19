from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 120.0,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    async def chat_with_tools(
        self, 
        system_instruction: str, 
        messages: list[dict[str, Any]], 
        tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "contents": messages,
            "generation_config": {
                "temperature": 0.2,
            },
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        
        url = f"{self.base_url}/models/{self.model}:generateContent"
        logger.info("Gemini request → %s", url)
        logger.debug("Payload: %s", json.dumps(payload, ensure_ascii=False, default=str)[:2000])
        
        max_retries = 4
        base_delay = 2.0  # seconds

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for attempt in range(max_retries):
                response = await client.post(url, headers=headers, json=payload)
                
                logger.info("Gemini response status: %s (attempt %d)", response.status_code, attempt + 1)
                
                if response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning("Gemini API Error [%s]. Retrying in %s seconds...", response.status_code, delay)
                    await asyncio.sleep(delay)
                    continue

                if not response.is_success:
                    logger.error("Gemini API Error [%s]: %s", response.status_code, response.text[:1000])
                    response.raise_for_status()
                
                break

            data = response.json()
            logger.debug("Gemini raw response: %s", json.dumps(data, ensure_ascii=False, default=str)[:2000])

        try:
            candidate = data["candidates"][0]
            parts = candidate["content"]["parts"]
            
            # Check for parallel function calls (multiple parts)
            function_calls = []
            for part in parts:
                if "functionCall" in part:
                    function_calls.append({
                        "name": part["functionCall"]["name"],
                        "args": part["functionCall"].get("args", {}),
                        "raw_call": part["functionCall"]
                    })
            
            if function_calls:
                logger.info("Gemini returned %d function call(s): %s", len(function_calls), [c['name'] for c in function_calls])
                for c in function_calls:
                    logger.info("  → %s(%s)", c['name'], c['args'])
                return {
                    "type": "function_calls",
                    "calls": function_calls,
                    "model_content": candidate["content"]
                }
            
            # Fallback: text response
            text_parts = [part["text"] for part in parts if "text" in part]
            if text_parts:
                combined = "\n".join(text_parts)
                logger.info("Gemini returned text (%d chars)", len(combined))
                return {
                    "type": "text",
                    "text": combined
                }
            
            raise ValueError("No recognizable response parts found")
                
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected Gemini response structure: {data}") from e
