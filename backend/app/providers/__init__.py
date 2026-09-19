"""LLM provider abstraction.

Two concrete channels share one interface so the translation/summary/QA
pipeline behaves identically on both:

  * OllamaProvider → local Ollama (default http://127.0.0.1:11434): zero token
    cost, works offline once the model weights are downloaded.
  * OpenAICompatProvider → any OpenAI-compatible endpoint (DeepSeek/OpenAI/…):
    billed per token, needs a key and a network connection.
  * OffProvider → AI features disabled ("关闭 AI · 纯阅读").

No key is ever logged, returned to the client, or written to the repo.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx

from app.config import settings


class ProviderError(RuntimeError):
    pass


class ProviderUnavailable(ProviderError):
    pass


@dataclass
class Capabilities:
    supports_json_schema: bool = False
    supports_stream: bool = True
    context_tokens: int = 8192
    is_local: bool = False
    rough_tokens_per_second: float = 0.0


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    model: str = ""
    provider: str = ""


def estimate_tokens(text: str) -> int:
    """Cheap heuristic: ~3.9 chars/token for English, ~1.6 for CJK."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(cjk / 1.6 + other / 3.9) + 1


class BaseProvider:
    name = "base"

    def __init__(
        self,
        provider_key: str,
        base_url: str,
        model: str,
        api_key: str = "",
        concurrency: int = 1,
    ) -> None:
        self.provider_key = provider_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.concurrency = max(1, concurrency)
        self._sem = asyncio.Semaphore(self.concurrency)
        self.last_usage = Usage()

    async def health(self) -> tuple[bool, str]:
        raise NotImplementedError

    def capabilities(self) -> Capabilities:
        return Capabilities()

    async def list_models(self) -> list[str]:
        return []

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        schema: Optional[dict] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> str:
        raise NotImplementedError

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        schema: Optional[dict] = None,
        temperature: float = 0.1,
    ) -> Any:
        """Return parsed JSON, tolerating models that wrap output in prose."""
        raw = await self.chat(messages, schema=schema, temperature=temperature)
        return extract_json(raw)

    async def _with_retries(self, fn, *, attempts: Optional[int] = None):
        tries = (attempts or settings.max_retries) + 1
        delay = 1.0
        last: Optional[Exception] = None
        for attempt in range(1, tries + 1):
            try:
                async with self._sem:
                    return await fn()
            except (httpx.HTTPError, ProviderError) as exc:  # transient
                last = exc
                if attempt >= tries:
                    break
                await asyncio.sleep(delay)
                delay *= 2
        raise ProviderError(f"{self.provider_key} 调用失败: {last}") from last


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(raw: str) -> Any:
    """Best-effort JSON recovery from an LLM response."""
    if raw is None:
        raise ProviderError("空响应")
    text = raw.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    match = _JSON_BLOCK.search(text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except Exception:
            pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                continue
    raise ProviderError("模型未返回可解析的 JSON")


class OllamaProvider(BaseProvider):
    """Local channel. Talks the Ollama HTTP API directly (no CLI needed)."""

    name = "local"

    def capabilities(self) -> Capabilities:
        return Capabilities(
            supports_json_schema=True,
            supports_stream=True,
            context_tokens=16384,
            is_local=True,
            rough_tokens_per_second=35.0,
        )

    async def health(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                models = [m.get("name", "") for m in resp.json().get("models", [])]
            if not models:
                return False, "Ollama 已启动，但尚未下载任何模型"
            base = self.model.split(":")[0]
            if any(m.split(":")[0] == base for m in models):
                return True, f"就绪 · 已安装 {len(models)} 个本地模型"
            return False, f"未找到模型 {self.model}（已安装：{', '.join(models[:4])}）"
        except Exception as exc:
            return False, f"未检测到本地推理服务（{type(exc).__name__}）"

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                return [m.get("name", "") for m in resp.json().get("models", [])]
        except Exception:
            return []

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        schema: Optional[dict] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": "10m",
            "options": {
                "temperature": temperature,
                "num_ctx": int(settings.chunk_token_budget * 3),
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        if schema:
            payload["format"] = schema

        async def call() -> str:
            started = time.perf_counter()
            async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                if resp.status_code >= 400:
                    raise ProviderError(f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
            self.last_usage = Usage(
                tokens_in=int(data.get("prompt_eval_count") or 0),
                tokens_out=int(data.get("eval_count") or 0),
                seconds=time.perf_counter() - started,
                model=self.model,
                provider="local",
            )
            return (data.get("message") or {}).get("content", "")

        return await self._with_retries(call)

    async def stream_chat(
        self, messages: list[dict[str, str]], *, temperature: float = 0.2
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature},
        }
        async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        continue
                    piece = (chunk.get("message") or {}).get("content", "")
                    if piece:
                        yield piece


class OpenAICompatProvider(BaseProvider):
    """Cloud channel: any OpenAI-compatible /chat/completions endpoint."""

    name = "cloud"

    def capabilities(self) -> Capabilities:
        return Capabilities(
            supports_json_schema=True,
            supports_stream=True,
            context_tokens=128000,
            is_local=False,
            rough_tokens_per_second=60.0,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def health(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "未配置云端 API Key"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{self.base_url}/models", headers=self._headers())
                if resp.status_code == 401:
                    return False, "云端 API Key 无效"
                resp.raise_for_status()
            return True, "云端通道可用"
        except Exception as exc:
            return False, f"云端不可达（{type(exc).__name__}），可改用本地通道"

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{self.base_url}/models", headers=self._headers())
                resp.raise_for_status()
                return [m.get("id", "") for m in resp.json().get("data", [])][:40]
        except Exception:
            return []

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        schema: Optional[dict] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if schema:
            payload["response_format"] = {"type": "json_object"}

        async def call() -> str:
            started = time.perf_counter()
            async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
                )
                if resp.status_code >= 400:
                    raise ProviderError(f"云端 HTTP {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
            usage = data.get("usage") or {}
            self.last_usage = Usage(
                tokens_in=int(usage.get("prompt_tokens") or 0),
                tokens_out=int(usage.get("completion_tokens") or 0),
                seconds=time.perf_counter() - started,
                model=self.model,
                provider="cloud",
            )
            return (data["choices"][0]["message"].get("content") or "").strip()

        return await self._with_retries(call)

    async def stream_chat(
        self, messages: list[dict[str, str]], *, temperature: float = 0.2
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
            async with client.stream(
                "POST", f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body in ("", "[DONE]"):
                        continue
                    try:
                        chunk = json.loads(body)
                    except Exception:
                        continue
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        yield piece


class OffProvider(BaseProvider):
    name = "off"

    def capabilities(self) -> Capabilities:
        return Capabilities(
            supports_json_schema=False, supports_stream=False, context_tokens=0
        )

    async def health(self) -> tuple[bool, str]:
        return False, "AI 功能已关闭（纯阅读模式）"

    async def chat(self, messages, *, schema=None, temperature=0.2, max_tokens=None) -> str:  # type: ignore[override]
        raise ProviderUnavailable("AI 功能已关闭：请在设置中启用本地模型或配置云端 API")


_registry: dict[str, BaseProvider] = {}


def build_provider(key: str) -> BaseProvider:
    cfg = settings.provider_config(key)
    if key == "local":
        return OllamaProvider(
            "local", cfg["base_url"], cfg["model"], cfg["api_key"], cfg["concurrency"]
        )
    if key == "cloud":
        return OpenAICompatProvider(
            "cloud", cfg["base_url"], cfg["model"], cfg["api_key"], cfg["concurrency"]
        )
    return OffProvider("off", "", "", "", 1)


def get_provider(key: str) -> BaseProvider:
    """Memoized so concurrency limits are shared across requests."""
    if key not in _registry:
        _registry[key] = build_provider(key)
    return _registry[key]


def refresh_provider(key: str) -> BaseProvider:
    _registry.pop(key, None)
    return get_provider(key)


def default_provider_key() -> str:
    return settings.llm_provider if settings.llm_provider in {"local", "cloud", "off"} else "off"


def estimate_cost_cny(tokens_in: int, tokens_out: int) -> float:
    return round(
        tokens_in / 1_000_000 * settings.cloud_price_in
        + tokens_out / 1_000_000 * settings.cloud_price_out,
        4,
    )
