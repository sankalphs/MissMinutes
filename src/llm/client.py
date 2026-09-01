"""OpenAI-compatible client for GMI serving (MiniMax-M3).

Used for: query parsing, entity/relationship/event/temporal extraction,
grounded answer synthesis, faithfulness checks. All outputs that touch
the graph must pass Pydantic validation first (spec:7,11,40).
"""
import json
import logging
import time
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
        # persistent client: connection reuse + transport-level retries
        # (the local DNS resolver drops lookups under concurrency)
        self._http = httpx.Client(
            timeout=timeout,
            transport=httpx.HTTPTransport(retries=3),
        )

    def close(self) -> None:
        self._http.close()

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 4096,
        retries: int = 4,
        model: str | None = None,
    ) -> str:
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                resp = self._http.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code == 402:
                    # not retryable: the key works but the model is not on plan
                    raise GMIError(f"HTTP 402 (model not on plan): {resp.text[:200]}")
                if resp.status_code == 429:
                    last_err = GMIError(f"HTTP 429: {resp.text[:200]}")
                    if attempt == retries:
                        break
                    retry_after = resp.headers.get("Retry-After")
                    # cap the wait — a server "Retry-After: 3600" must never
                    # park a worker thread for an hour
                    wait = min(
                        int(retry_after) if retry_after and retry_after.isdigit() else 2 * (attempt + 1),
                        30,
                    )
                    logger.info("429 rate limit — sleeping %ss (attempt %d)", wait, attempt)
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    last_err = GMIError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                    if attempt == retries:
                        break
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if resp.status_code >= 400:
                    # other 4xx (bad key, bad request) never succeed on retry —
                    # fail fast instead of burning attempts and sleep time
                    raise GMIError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                try:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError):
                    raise GMIError(f"malformed response body: {resp.text[:300]}")
                if content is None:
                    # reasoning models can return null content, e.g. on
                    # finish_reason=length — a None reaching callers crashes
                    # .strip() far from the cause
                    finish = data["choices"][0].get("finish_reason", "unknown")
                    raise GMIError(f"model returned no content (finish_reason={finish})")
                return content
            except httpx.HTTPError as e:
                # transport errors (DNS, connect, read) are retryable
                last_err = e
                if attempt == retries:
                    break
                time.sleep(1.5 * (attempt + 1))
        raise GMIError(f"GMI request failed after {retries + 1} attempts: {last_err}")

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 4096,
        json_repair_attempt: bool = True,
    ) -> Any:
        """Chat expecting a JSON object response; strips code fences.

        On parse failure, retries once asking the model to re-emit valid
        compact JSON (fixes truncation/quote glitches).
        """
        content = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            if not json_repair_attempt:
                raise GMIError(f"Invalid JSON from model: {content[:500]}")
            repaired = self.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "You fix malformed JSON. Output ONLY the corrected, "
                            "valid compact JSON object. No prose, no code fences."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                temperature=0.0,
                # repair re-emits the original payload, not a full answer
                max_tokens=min(max_tokens, 600),
            )
            rtext = repaired.strip()
            if rtext.startswith("```"):
                rtext = rtext.split("\n", 1)[1] if "\n" in rtext else rtext
                rtext = rtext.rsplit("```", 1)[0]
            try:
                return json.loads(rtext)
            except json.JSONDecodeError as e:
                raise GMIError(f"JSON repair failed: {e}\n{content[:500]}") from e
