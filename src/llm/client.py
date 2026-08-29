"""OpenAI-compatible client for GMI serving (MiniMax-M3).

Used for: query parsing, entity/relationship/event/temporal extraction,
grounded answer synthesis, faithfulness checks. All outputs that touch
the graph must pass Pydantic validation first (spec:7,11,40).
"""
import json
import logging
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class GMIError(Exception):
    pass


class GMIClient:
    def __init__(self, timeout: float = 120.0) -> None:
        self.base_url = settings.GMI_BASE_URL.rstrip("/")
        self.api_key = settings.GMI_API_KEY
        self.model = settings.GMI_MODEL
        self.timeout = timeout

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 4096,
        retries: int = 2,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                resp = httpx.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_err = GMIError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except httpx.HTTPError as e:
                last_err = e
        raise GMIError(f"GMI request failed after {retries + 1} attempts: {last_err}")

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> Any:
        """Chat expecting a JSON object response; strips code fences."""
        content = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0]
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise GMIError(f"Invalid JSON from model: {e}\n{content[:500]}") from e
