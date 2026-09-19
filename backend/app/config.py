"""Application configuration for Essay Reader.

All tunables are environment-driven so the app can run fully offline with a
local model, or against any OpenAI-compatible cloud endpoint.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]          # backend/
PROJECT_ROOT = BASE_DIR.parent                          # repo root
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
DATA_DIR = Path(os.environ.get("ESSAY_DATA_DIR", BASE_DIR / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
ASSET_DIR = DATA_DIR / "assets"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "essay_reader.sqlite3"

for _d in (DATA_DIR, UPLOAD_DIR, ASSET_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Settings:
    """Runtime settings, read once at import time."""

    # --- parse pipeline ---
    render_dpi: int = _env_int("ESSAY_RENDER_DPI", 200)
    figure_min_area_ratio: float = float(os.environ.get("ESSAY_FIGURE_MIN_AREA_RATIO", "0.012"))
    column_min_gap_ratio: float = float(os.environ.get("ESSAY_COLUMN_MIN_GAP_RATIO", "0.035"))
    max_upload_mb: int = _env_int("ESSAY_MAX_UPLOAD_MB", 200)

    # --- OCR fallback (local, offline) ---
    ocr_enabled: bool = _env_bool("ESSAY_OCR_ENABLED", True)
    ocr_dpi: int = _env_int("ESSAY_OCR_DPI", 200)
    ocr_num_threads: int = _env_int("ESSAY_OCR_THREADS", 2)
    ocr_min_confidence: float = float(os.environ.get("ESSAY_OCR_MIN_CONFIDENCE", "0.5"))
    # Pages with fewer characters than this are candidates for OCR.
    ocr_min_text_chars: int = _env_int("ESSAY_OCR_MIN_TEXT_CHARS", 240)
    # "auto" runs OCR only on scanned-looking pages; "off" disables it entirely.
    ocr_mode: str = os.environ.get("ESSAY_OCR_MODE", "auto").strip().lower()

    # --- guided setup for the local channel ---
    ollama_installer_url: str = os.environ.get(
        "OLLAMA_INSTALLER_URL", "https://ollama.com/download/OllamaSetup.exe"
    )
    ollama_download_page: str = os.environ.get(
        "OLLAMA_DOWNLOAD_PAGE", "https://ollama.com/download"
    )
    ollama_linux_command: str = os.environ.get(
        "OLLAMA_LINUX_COMMAND", "curl -fsSL https://ollama.com/install.sh | sh"
    )

    # --- provider / channel ---
    # local | cloud | off
    llm_provider: str = os.environ.get("LLM_PROVIDER", "off").strip().lower()
    local_base_url: str = os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    local_model: str = os.environ.get("LOCAL_LLM_MODEL", "qwen3:8b")
    local_vision_model: str = os.environ.get("LOCAL_LLM_VISION_MODEL", "")
    cloud_base_url: str = os.environ.get("CLOUD_LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    cloud_model: str = os.environ.get("CLOUD_LLM_MODEL", "deepseek-chat")
    cloud_api_key: str = os.environ.get("CLOUD_LLM_API_KEY", "")

    # --- concurrency budget (local channel stays conservative) ---
    local_concurrency: int = _env_int("ESSAY_LOCAL_CONCURRENCY", 1)
    cloud_concurrency: int = _env_int("ESSAY_CLOUD_CONCURRENCY", 4)
    request_timeout_s: int = _env_int("ESSAY_REQUEST_TIMEOUT_S", 180)
    max_retries: int = _env_int("ESSAY_MAX_RETRIES", 2)
    chunk_token_budget: int = _env_int("ESSAY_CHUNK_TOKEN_BUDGET", 1200)
    context_paragraphs: int = _env_int("ESSAY_CONTEXT_PARAGRAPHS", 2)
    token_budget_per_doc: int = _env_int("ESSAY_TOKEN_BUDGET_PER_DOC", 0)  # 0 = unlimited
    quality_retry_limit: int = _env_int("ESSAY_QUALITY_RETRY_LIMIT", 1)

    # rough price table (CNY per 1M tokens) used only for cost estimates
    cloud_price_in: float = float(os.environ.get("CLOUD_PRICE_IN_PER_M", "1.0"))
    cloud_price_out: float = float(os.environ.get("CLOUD_PRICE_OUT_PER_M", "2.0"))

    def provider_config(self, provider: str) -> dict:
        if provider == "local":
            return {
                "base_url": self.local_base_url,
                "model": self.local_model,
                "api_key": "",
                "concurrency": self.local_concurrency,
            }
        if provider == "cloud":
            return {
                "base_url": self.cloud_base_url,
                "model": self.cloud_model,
                "api_key": self.cloud_api_key,
                "concurrency": self.cloud_concurrency,
            }
        return {"base_url": "", "model": "", "api_key": "", "concurrency": 1}

    # -- runtime updates (settings are editable from the UI without a restart) --
    def apply_overrides(self, values: dict) -> list[str]:
        changed: list[str] = []
        mapping = {
            "llm_provider": ("llm_provider", str),
            "local_base_url": ("local_base_url", str),
            "local_model": ("local_model", str),
            "cloud_base_url": ("cloud_base_url", str),
            "cloud_model": ("cloud_model", str),
            "cloud_api_key": ("cloud_api_key", str),
            "local_concurrency": ("local_concurrency", int),
            "cloud_concurrency": ("cloud_concurrency", int),
            "chunk_token_budget": ("chunk_token_budget", int),
            "context_paragraphs": ("context_paragraphs", int),
            "token_budget_per_doc": ("token_budget_per_doc", int),
            "request_timeout_s": ("request_timeout_s", int),
            "max_retries": ("max_retries", int),
            "quality_retry_limit": ("quality_retry_limit", int),
            "cloud_price_in": ("cloud_price_in", float),
            "cloud_price_out": ("cloud_price_out", float),
            "ocr_enabled": ("ocr_enabled", bool),
            "ocr_mode": ("ocr_mode", str),
            "ocr_dpi": ("ocr_dpi", int),
            "ocr_min_text_chars": ("ocr_min_text_chars", int),
        }
        for key, (attr, caster) in mapping.items():
            if key not in values or values[key] is None:
                continue
            raw = values[key]
            if caster is bool and isinstance(raw, str):
                raw = raw.strip().lower() in {"1", "true", "yes", "on"}
            try:
                parsed = caster(raw) if not isinstance(raw, str) or caster is str else caster(raw.strip())
            except (TypeError, ValueError):
                continue
            if caster is str:
                parsed = str(parsed).strip()
                if attr.endswith("base_url"):
                    parsed = parsed.rstrip("/")
            if getattr(self, attr) != parsed:
                setattr(self, attr, parsed)
                changed.append(attr)
        return changed

    def public_dict(self) -> dict:
        """Never expose the API key itself, only whether one is configured."""
        return {
            "llm_provider": self.llm_provider,
            "local_base_url": self.local_base_url,
            "local_model": self.local_model,
            "cloud_base_url": self.cloud_base_url,
            "cloud_model": self.cloud_model,
            "cloud_api_key_set": bool(self.cloud_api_key),
            "local_concurrency": self.local_concurrency,
            "cloud_concurrency": self.cloud_concurrency,
            "chunk_token_budget": self.chunk_token_budget,
            "context_paragraphs": self.context_paragraphs,
            "token_budget_per_doc": self.token_budget_per_doc,
            "request_timeout_s": self.request_timeout_s,
            "max_retries": self.max_retries,
            "quality_retry_limit": self.quality_retry_limit,
            "cloud_price_in": self.cloud_price_in,
            "cloud_price_out": self.cloud_price_out,
            "render_dpi": self.render_dpi,
            "ocr_enabled": self.ocr_enabled,
            "ocr_mode": self.ocr_mode,
            "ocr_dpi": self.ocr_dpi,
            "ocr_min_text_chars": self.ocr_min_text_chars,
        }


settings = Settings()
