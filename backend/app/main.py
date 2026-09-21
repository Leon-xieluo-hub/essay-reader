"""FastAPI application: parsing, translation, summary, QA, notes, settings.

Everything runs locally against SQLite + the filesystem. The only outbound
traffic is (a) the one-time local model download and (b) the optional cloud
channel when the user explicitly selects it.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.config import ASSET_DIR, DATA_DIR, FRONTEND_DIST, UPLOAD_DIR, settings
from app.parsing import file_sha256, ocr_status, parse_pdf
from app.providers import (
    ProviderUnavailable,
    estimate_cost_cny,
    estimate_tokens,
    get_provider,
    refresh_provider,
)
from app.schemas import (
    AskRequest,
    BlockOut,
    Document,
    DocumentMeta,
    GlossaryTerm,
    GlossaryTermIn,
    Note,
    NoteIn,
    ProviderStatus,
    SummaryRequest,
    TaskState,
    TranslateRequest,
    TranslationMeta,
    UsageStats,
)
from app.services import summary as summary_service
from app.services import translate as translate_service

app = FastAPI(title="Essay Reader API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Settings the UI may change and that should survive a restart.
_PERSISTED_SETTINGS = {
    "llm_provider",
    "local_base_url",
    "local_model",
    "cloud_base_url",
    "cloud_model",
    "cloud_api_key",
    "local_concurrency",
    "cloud_concurrency",
    "chunk_token_budget",
    "context_paragraphs",
    "token_budget_per_doc",
    "request_timeout_s",
    "max_retries",
    "quality_retry_limit",
    "cloud_price_in",
    "cloud_price_out",
    "ocr_enabled",
    "ocr_mode",
    "ocr_dpi",
    "ocr_min_text_chars",
}


def _force_utf8_logging() -> None:
    """Make console logging UTF-8 regardless of how the server was launched.

    On Chinese Windows the console defaults to code page 936 (GBK) while Python
    emits UTF-8, so anything non-ASCII in a log line (our parse warnings are
    Chinese) turns into mojibake in the launcher window. Reconfiguring is a no-op
    when the stream is already UTF-8.
    """
    import logging

    streams = [sys.stdout, sys.stderr]
    for logger_name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(logger_name).handlers:
            stream = getattr(handler, "stream", None)
            if stream is not None:
                streams.append(stream)
    for stream in streams:
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


_force_utf8_logging()

# ------------------------------------------------------------------ task queue
_TASKS: dict[str, TaskState] = {}
# Local inference and heavy CPU work never run on the same GPU/VRAM budget at
# once, so the local channel serializes through this lock.
_LOCAL_GPU_LOCK = asyncio.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


async def _new_task(doc_id: str, kind: str, provider: str = "") -> TaskState:
    task = TaskState(
        id=uuid.uuid4().hex[:12],
        doc_id=doc_id,
        kind=kind,
        provider=provider,
        status="running",
        started_at=_now(),
    )
    _TASKS[task.id] = task
    return task


async def _run_task(task: TaskState, coro) -> None:
    try:
        result = await coro
        task.status = "done"
        task.message = json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)
        if isinstance(result, dict):
            task.total = int(result.get("total") or task.total or 0)
            task.done = int(result.get("done") or task.done or task.total)
    except ProviderUnavailable as exc:
        task.status = "error"
        task.error = str(exc)
    except asyncio.CancelledError:
        task.status = "cancelled"
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI verbatim
        task.status = "error"
        task.error = f"{type(exc).__name__}: {exc}"
    finally:
        task.finished_at = _now()


@app.on_event("startup")
async def _startup() -> None:
    db.connect()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Settings saved from the UI (cloud key, model names, concurrency…) are
    # persisted in SQLite and re-applied on boot so a restart does not silently
    # drop the user's channel configuration.
    stored = db.load_settings()
    if stored:
        settings.apply_overrides(stored)
        for key in ("local", "cloud"):
            refresh_provider(key)


# --------------------------------------------------------------------- health


def _internet_available(timeout: float = 1.5) -> bool:
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=timeout).close()
        return True
    except OSError:
        return False


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "time": _now(), "data_dir": str(DATA_DIR)}


@app.get("/api/providers", response_model=list[ProviderStatus])
async def providers() -> list[ProviderStatus]:
    out: list[ProviderStatus] = []
    for key in ("local", "cloud"):
        provider = get_provider(key)
        ok, detail = await provider.health()
        models = await provider.list_models() if key == "local" else []
        out.append(
            ProviderStatus(
                name=key,
                available=ok,
                detail=detail,
                model=provider.model,
                base_url=provider.base_url,
                is_local=key == "local",
                installed_models=models,
            )
        )
    return out


@app.get("/api/environment")
async def environment() -> dict:
    ocr_ready, ocr_detail = ocr_status()
    return {
        "internet": _internet_available(),
        "provider": settings.llm_provider,
        "offline_capable": True,
        "ocr": {"available": ocr_ready, "detail": ocr_detail, "mode": settings.ocr_mode},
        "configured": settings.public_dict(),
    }


# ------------------------------------------------------------------ documents


def _block_to_out(block, translations: dict, note_counts: dict[str, int]) -> BlockOut:
    variants = translations.get(block.id, [])
    tr = {v["provider"]: v["text"] for v in variants if (v["text"] or "").strip()}
    meta = {
        v["provider"]: TranslationMeta(
            provider=v["provider"],
            model=v["model"],
            lang=v["lang"],
            quality=v["quality"],
            attempts=v["attempts"],
        )
        for v in variants
    }
    return BlockOut(
        id=block.id,
        order=block.order,
        page=block.page,
        type=block.type,
        text=block.text,
        bbox=block.bbox,
        column=block.column,
        level=block.level,
        size=block.size,
        image_url=f"/assets/{block.image_path}" if block.image_path else None,
        latex=block.latex,
        caption=block.caption,
        table_html=block.table_html,
        table_rows=block.table_rows,
        table_rows_translated=block.table_rows_translated,
        emphasis=block.emphasis,
        flags=block.flags,
        translations=tr,
        translation_meta=meta,
        note_count=note_counts.get(block.id, 0),
    )


@app.get("/api/documents", response_model=list[DocumentMeta])
async def list_documents() -> list[DocumentMeta]:
    return db.list_documents()


@app.post("/api/documents", response_model=Document)
async def upload_document(
    file: UploadFile = File(...),
    ocr: str = Query("auto", description="OCR 兜底：auto 仅处理扫描页 / force 全页 OCR / off 关闭"),
) -> Document:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "只支持 PDF 文件")
    doc_id = uuid.uuid4().hex[:12]
    target = UPLOAD_DIR / f"{doc_id}.pdf"
    size = 0
    with target.open("wb") as handle:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > settings.max_upload_mb * 1024 * 1024:
                handle.close()
                target.unlink(missing_ok=True)
                raise HTTPException(413, f"文件超过 {settings.max_upload_mb}MB 上限")
            handle.write(chunk)

    digest = file_sha256(target)
    existing = db.find_document_by_hash(digest)
    if existing:
        target.unlink(missing_ok=True)
        data = db.get_document(existing.id)
        if data:
            return Document(**data)

    started = time.perf_counter()
    # OCR runs on CPU only, so it never contends with GPU inference; it just
    # makes parsing slower, so the mode is explicit per upload.
    mode = ocr.strip().lower()
    use_ocr = mode in {"auto", "force", "1", "true", "on"}
    force_ocr = mode == "force"
    try:
        blocks, pages, report, meta = await asyncio.to_thread(
            parse_pdf, target, doc_id, use_ocr, force_ocr
        )
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(422, f"PDF 解析失败：{type(exc).__name__}: {exc}") from exc

    if report.paragraph_count == 0:
        report.warnings.append("未提取到正文段落；如为扫描件请在设置中开启 OCR 兜底后重新上传")

    db.insert_document(
        doc_id=doc_id,
        filename=file.filename,
        sha256=digest,
        file_size=size,
        pages=pages,
        report=report,
        title=meta.get("title", ""),
        authors=meta.get("authors", []),
    )
    db.insert_blocks(blocks)
    report.duration_ms = int((time.perf_counter() - started) * 1000)
    db.update_document_report(doc_id, report)
    data = db.get_document(doc_id)
    if not data:
        raise HTTPException(500, "文档写入失败")
    return Document(**data)


@app.get("/api/documents/{doc_id}", response_model=Document)
async def get_document(doc_id: str) -> Document:
    data = db.get_document(doc_id)
    if not data:
        raise HTTPException(404, "文档不存在")
    return Document(**data)


@app.get("/api/documents/{doc_id}/blocks", response_model=list[BlockOut])
async def get_blocks(
    doc_id: str,
    lang: str = Query("zh"),
    with_translations: bool = Query(True),
    kinds: str = Query("", description="逗号分隔的 block 类型过滤"),
) -> list[BlockOut]:
    if not db.get_document(doc_id):
        raise HTTPException(404, "文档不存在")
    blocks = db.get_blocks(doc_id)
    translations = db.get_translations(doc_id, lang) if with_translations else {}
    note_counts: dict[str, int] = {}
    for note in db.get_notes(doc_id):
        note_counts[note.block_id] = note_counts.get(note.block_id, 0) + 1
    allowed = {k for k in kinds.split(",") if k} if kinds else None
    return [
        _block_to_out(b, translations, note_counts)
        for b in blocks
        if allowed is None or b.type in allowed
    ]


@app.get("/api/documents/{doc_id}/file")
async def get_document_file(doc_id: str) -> FileResponse:
    data = db.get_document(doc_id)
    if not data:
        raise HTTPException(404, "文档不存在")
    path = UPLOAD_DIR / f"{doc_id}.pdf"
    if not path.exists():
        raise HTTPException(404, "原始 PDF 已丢失")
    return FileResponse(path, media_type="application/pdf", filename=data["filename"])


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str) -> dict:
    db.delete_document(doc_id)
    (UPLOAD_DIR / f"{doc_id}.pdf").unlink(missing_ok=True)
    shutil.rmtree(ASSET_DIR / doc_id, ignore_errors=True)
    return {"ok": True}


@app.get("/api/documents/{doc_id}/export")
async def export_markdown(
    doc_id: str, lang: str = Query("zh"), mode: str = Query("bilingual")
) -> StreamingResponse:
    data = db.get_document(doc_id)
    if not data:
        raise HTTPException(404, "文档不存在")
    blocks = db.get_blocks(doc_id)
    translations = db.get_translations(doc_id, lang)
    notes = db.get_notes(doc_id)
    summary = db.get_summary(doc_id, lang)

    lines = [f"# {data.get('title') or data['filename']}", ""]
    if data.get("authors"):
        lines += ["**作者**：" + ", ".join(data["authors"]), ""]
    if summary:
        lines += ["> 由 Essay Reader 生成的结构化要点", "", summary["content"], "", "---", ""]
    for block in blocks:
        if block.type in ("header", "footer"):
            continue
        variants = translations.get(block.id, [])
        translated = variants[0]["text"] if variants else ""
        if block.type == "heading":
            level = min(6, max(1, block.level or 2))
            text = block.text.strip()
            if mode != "original" and translated:
                text = f"{text} / {translated}"
            lines += ["#" * level + " " + text, ""]
            continue
        if block.type == "figure":
            if block.image_path:
                lines += [f"![figure](/assets/{block.image_path})", ""]
            if block.caption:
                lines += [f"*{block.caption}*", ""]
            continue
        if block.type == "table" and block.table_rows:
            header = block.table_rows[0]
            lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
            for row in block.table_rows[1:]:
                lines += ["| " + " | ".join(row) + " |"]
            lines += [""]
            continue
        text = block.text.strip()
        if not text:
            continue
        if mode == "original" or not translated:
            lines += [text, ""]
        elif mode == "translated":
            lines += [translated, ""]
        else:
            lines += [text, "", f"> {translated}", ""]
    if notes:
        lines += ["---", "", "## 笔记", ""]
        for note in notes:
            lines += [f"- {note.comment}", f"  > {note.quote}", ""]
    content = "\n".join(lines)
    return StreamingResponse(
        iter([content]),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{doc_id}.md"'},
    )


# ------------------------------------------------------------------ translate


@app.post("/api/translate", response_model=TaskState)
async def translate(req: TranslateRequest) -> TaskState:
    if not db.get_document(req.doc_id):
        raise HTTPException(404, "文档不存在")
    task = await _new_task(req.doc_id, "translate", req.provider)
    provider_key = req.provider

    async def job() -> dict:
        async def progress(done: int, total: int, message: str) -> None:
            task.done, task.total, task.message = done, total, message

        async def run() -> dict:
            # Fail fast with an actionable message instead of a long retry storm.
            ready, detail = await get_provider(provider_key).health()
            if not ready:
                raise ProviderUnavailable(f"{provider_key} 通道不可用：{detail}")
            if not db.get_glossary(req.doc_id):
                await translate_service.build_glossary(req.doc_id, provider_key, req.lang)
            return await translate_service.translate_document(
                doc_id=req.doc_id,
                provider_key=provider_key,
                lang=req.lang,
                style=req.style,
                block_ids=req.block_ids,
                force=req.force,
                progress=progress,
            )

        if provider_key == "local":
            async with _LOCAL_GPU_LOCK:
                return await run()
        return await run()

    asyncio.create_task(_run_task(task, job()))
    return task


@app.post("/api/translate/estimate")
async def translate_estimate(req: TranslateRequest) -> dict:
    blocks = translate_service.select_blocks(db.get_blocks(req.doc_id), req.block_ids)
    chunks = translate_service.chunk_blocks(blocks)
    text_tokens = 0
    table_tokens = 0
    for block in blocks:
        if block.type == "table":
            table_tokens += estimate_tokens(translate_service._table_plain_text(block))
        else:
            text_tokens += estimate_tokens(block.text)
    # Calibrated against a real 17-page paper (measured: in 39.1k / out 17.5k).
    # Input needs per-chunk overhead (system prompt + glossary + neighbour context);
    # output runs ~1.3x the token estimate because Chinese prose uses more tokens
    # per character than the estimator assumes.
    tokens_in = text_tokens + len(chunks) * 700
    tokens_out = int((text_tokens + table_tokens) * 0.95 * 1.3)
    return {
        "blocks": len(blocks),
        "chunks": len(chunks),
        "estimated_tokens_in": tokens_in,
        "estimated_tokens_out": tokens_out,
        "estimated_cost_cny": estimate_cost_cny(tokens_in, tokens_out),
        "local_eta_seconds": int(tokens_out / 30.0) + len(chunks) * 2,
    }


# -------------------------------------------------------------------- summary


@app.post("/api/summary", response_model=TaskState)
async def create_summary(req: SummaryRequest) -> TaskState:
    if not db.get_document(req.doc_id):
        raise HTTPException(404, "文档不存在")
    task = await _new_task(req.doc_id, "summary", req.provider)

    async def job() -> dict:
        async def run() -> dict:
            ready, detail = await get_provider(req.provider).health()
            if not ready:
                raise ProviderUnavailable(f"{req.provider} 通道不可用：{detail}")
            return await summary_service.summarize_document(
                doc_id=req.doc_id, provider_key=req.provider, lang=req.lang, force=req.force
            )

        if req.provider == "local":
            async with _LOCAL_GPU_LOCK:
                return await run()
        return await run()

    asyncio.create_task(_run_task(task, job()))
    return task


@app.get("/api/summary/{doc_id}")
async def get_summary(doc_id: str, lang: str = Query("zh")) -> dict:
    data = db.get_summary(doc_id, lang)
    if not data:
        return {"content": "", "provider": "", "model": ""}
    return data


# ------------------------------------------------------------------------- QA


@app.post("/api/ask")
async def ask(req: AskRequest) -> dict:
    async def run() -> dict:
        return await summary_service.ask_document(
            doc_id=req.doc_id,
            question=req.question,
            provider_key=req.provider,
            lang=req.lang,
            block_ids=req.block_ids,
            top_k=req.top_k,
        )

    if req.provider == "local":
        async with _LOCAL_GPU_LOCK:
            return await run()
    return await run()


# ---------------------------------------------------------------------- notes


@app.get("/api/notes/{doc_id}", response_model=list[Note])
async def list_notes(doc_id: str) -> list[Note]:
    return db.get_notes(doc_id)


@app.post("/api/notes", response_model=Note)
async def create_note(note: NoteIn) -> Note:
    note_id = db.insert_note(
        doc_id=note.doc_id,
        block_id=note.block_id,
        quote=note.quote,
        comment=note.comment,
        color=note.color,
    )
    for item in db.get_notes(note.doc_id):
        if item.id == note_id:
            return item
    raise HTTPException(500, "笔记写入失败")


@app.put("/api/notes/{note_id}")
async def update_note(note_id: int, comment: str = Body(..., embed=True)) -> dict:
    db.update_note(note_id, comment)
    return {"ok": True}


@app.delete("/api/notes/{note_id}")
async def delete_note(note_id: int) -> dict:
    db.delete_note(note_id)
    return {"ok": True}


# ------------------------------------------------------------------- glossary


@app.get("/api/glossary/{doc_id}", response_model=list[GlossaryTerm])
async def get_glossary(doc_id: str) -> list[GlossaryTerm]:
    return db.get_glossary(doc_id)


@app.post("/api/glossary", response_model=list[GlossaryTerm])
async def upsert_glossary(term: GlossaryTermIn, doc_id: str = Query(...)) -> list[GlossaryTerm]:
    db.upsert_glossary(doc_id, term.source.strip(), term.target.strip(), term.note, locked=True)
    return db.get_glossary(doc_id)


@app.delete("/api/glossary/{doc_id}/{term_id}")
async def delete_glossary(doc_id: str, term_id: int) -> dict:
    db.delete_glossary_term(doc_id, term_id)
    return {"ok": True}


@app.post("/api/glossary/{doc_id}/build")
async def build_glossary(
    doc_id: str, provider: str = Query("local"), lang: str = Query("zh")
) -> dict:
    terms = await translate_service.build_glossary(doc_id, provider, lang)
    return {"terms": terms}


# ------------------------------------------------------------------- settings


@app.get("/api/settings")
async def get_settings() -> dict:
    return settings.public_dict()


@app.put("/api/settings")
async def update_settings(payload: dict = Body(...)) -> dict:
    changed = settings.apply_overrides(payload)
    for key in ("local", "cloud"):
        refresh_provider(key)
    # persist so the configuration survives a restart (empty values are skipped
    # so saving a blank key field never wipes a stored secret)
    to_store = {
        key: value
        for key, value in payload.items()
        if key in _PERSISTED_SETTINGS and value is not None and str(value).strip() != ""
    }
    if to_store:
        db.save_settings(to_store)
    return {"changed": changed, "settings": settings.public_dict()}


@app.get("/api/settings/stored")
async def stored_settings() -> dict:
    """Which settings are persisted (values are not returned for secrets)."""
    stored = db.load_settings()
    return {
        "keys": sorted(stored.keys()),
        "cloud_api_key_stored": bool(stored.get("cloud_api_key")),
    }


@app.get("/api/usage", response_model=UsageStats)
async def usage() -> UsageStats:
    totals = db.usage_totals()
    return UsageStats(
        cloud_tokens_in=totals["cloud_tokens_in"],
        cloud_tokens_out=totals["cloud_tokens_out"],
        cloud_estimated_cost_cny=estimate_cost_cny(
            totals["cloud_tokens_in"], totals["cloud_tokens_out"]
        ),
        local_blocks_translated=totals["local_blocks_translated"],
        local_seconds=round(totals["local_seconds"], 1),
    )


@app.post("/api/usage/reset")
async def reset_usage() -> dict:
    db.reset_usage()
    return {"ok": True}


# --------------------------------------------------------------------- models


@app.post("/api/models/pull")
async def pull_model(payload: dict = Body(...)) -> StreamingResponse:
    """Stream `ollama pull` progress so the UI can show a one-time download."""
    model = str(payload.get("model", "")).strip() or settings.local_model
    if not model:
        raise HTTPException(400, "未指定模型")

    async def stream():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST", f"{settings.local_base_url}/api/pull", json={"name": model, "stream": True}
                ) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        yield f"data: {json.dumps({'error': body.decode('utf-8', 'ignore')[:300]})}\n\n"
                        return
                    async for line in resp.aiter_lines():
                        if line.strip():
                            yield f"data: {line.strip()}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': f'{type(exc).__name__}: {exc}'})}\n\n"
            yield f"data: {json.dumps({'done': True, 'failed': True})}\n\n"
            return
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/models")
async def list_models() -> dict:
    return {"installed": await get_provider("local").list_models(), "current": settings.local_model}


# --------------------------------------------------------------- guided setup


@app.get("/api/setup/guide")
async def setup_guide() -> dict:
    """Diagnose each channel and return concrete, actionable next steps."""
    local_provider = get_provider("local")
    cloud_provider = get_provider("cloud")
    local_ok, local_detail = await local_provider.health()
    cloud_ok, cloud_detail = await cloud_provider.health()
    models = await local_provider.list_models()

    platform = sys.platform
    installer_path = ""
    for candidate in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Ollama" / "ollama.exe",
    ):
        try:
            if candidate.is_file():
                installer_path = str(candidate)
                break
        except OSError:
            continue
    if not installer_path:
        installer_path = shutil.which("ollama") or ""

    return {
        "platform": platform,
        "local": {
            "available": local_ok,
            "detail": local_detail,
            "model": local_provider.model,
            "base_url": local_provider.base_url,
            "binary_found": bool(installer_path),
            "binary_path": installer_path,
            "installed_models": models,
            "needs": (
                "ready"
                if local_ok
                else ("install_runtime" if not installer_path else "pull_model")
            ),
        },
        "cloud": {
            "available": cloud_ok,
            "detail": cloud_detail,
            "model": cloud_provider.model,
            "base_url": cloud_provider.base_url,
            "api_key_set": bool(settings.cloud_api_key),
        },
        "links": {
            "ollama_download": settings.ollama_download_page,
            "ollama_installer": settings.ollama_installer_url,
            "ollama_models": "https://ollama.com/library",
            "openai_compatible_docs": "https://platform.openai.com/docs/api-reference",
            "deepseek_keys": "https://platform.deepseek.com/api_keys",
        },
        "commands": {
            "windows_install": "OllamaSetup.exe /SILENT",
            "linux_install": settings.ollama_linux_command,
            "pull_model": f"ollama pull {local_provider.model}",
        },
    }


@app.post("/api/setup/download-ollama")
async def download_ollama(payload: dict = Body(default={})) -> StreamingResponse:
    """Download the Ollama installer with progress, so setup is one click.

    The file is only downloaded and stored locally — installing it stays an
    explicit user action on their own machine.
    """
    url = str(payload.get("url") or settings.ollama_installer_url)
    if not url.lower().startswith("https://"):
        raise HTTPException(400, "只允许 https 下载地址")
    target_dir = DATA_DIR / "downloads"
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = url.rstrip("/").split("/")[-1] or "OllamaSetup.exe"
    if not filename.lower().endswith((".exe", ".msi", ".zip")):
        filename = "OllamaSetup.exe"
    target = target_dir / filename

    async def event_stream():
        downloaded = 0
        try:
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code >= 400:
                        yield f"data: {json.dumps({'error': f'HTTP {response.status_code}'})}\n\n"
                        return
                    total = int(response.headers.get("content-length") or 0)
                    with target.open("wb") as handle:
                        async for chunk in response.aiter_bytes(1 << 18):
                            handle.write(chunk)
                            downloaded += len(chunk)
                            percent = int(downloaded / total * 100) if total else 0
                            yield (
                                "data: "
                                + json.dumps(
                                    {
                                        "downloaded": downloaded,
                                        "total": total,
                                        "percent": percent,
                                        "done": False,
                                    }
                                )
                                + "\n\n"
                            )
        except Exception as exc:
            yield f"data: {json.dumps({'error': f'{type(exc).__name__}: {exc}'})}\n\n"
            yield f"data: {json.dumps({'done': True, 'failed': True})}\n\n"
            return
        yield (
            "data: "
            + json.dumps(
                {"done": True, "path": str(target), "size": downloaded, "percent": 100}
            )
            + "\n\n"
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/tasks/{task_id}", response_model=TaskState)
async def get_task(task_id: str) -> TaskState:
    task = _TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@app.get("/api/tasks", response_model=list[TaskState])
async def list_tasks() -> list[TaskState]:
    return sorted(_TASKS.values(), key=lambda t: t.started_at, reverse=True)[:50]


# ---------------------------------------------------------------------- assets


@app.get("/assets/{path:path}")
async def assets(path: str):
    """Serves two things under one prefix: figure crops and the SPA bundle.

    Figure crops live in the data directory; the Vite bundle lives in
    `frontend/dist/assets`. Data assets win so a document can never shadow the
    app's own JavaScript.

    Cache headers matter here: the bundle name carries a content hash, so it can
    be cached forever, while a rebuilt bundle must never be masked by a stale
    entry in the browser (that is how a UI change goes missing).
    """
    for base, cache in (
        (ASSET_DIR.resolve(), "public, max-age=86400"),
        ((FRONTEND_DIST / "assets").resolve(), "public, max-age=31536000, immutable"),
    ):
        candidate = (base / path).resolve()
        if str(candidate).startswith(str(base)) and candidate.is_file():
            return FileResponse(candidate, headers={"Cache-Control": cache})
    raise HTTPException(404, "资源不存在")


# ------------------------------------------------------- bundled frontend SPA
# `npm run build` output is served from the same origin as the API, so the whole
# app runs on one port with no dev server and no network access.

_INDEX_FILE = FRONTEND_DIST / "index.html"
# The shell is never cached: after `npm run build` the browser must pick up the
# new bundle hash immediately instead of reusing a heuristically fresh copy.
_NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}

if _INDEX_FILE.exists():
    app.mount("/app", StaticFiles(directory=FRONTEND_DIST), name="spa")

    @app.get("/")
    async def spa_root() -> FileResponse:
        return FileResponse(_INDEX_FILE, headers=_NO_CACHE)

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        # Real build artifacts win; everything else returns the shell so hash
        # routes keep working. Note the bundle lives in `assets/` while
        # `/assets/*` is also the figure-crop endpoint, so look in both places.
        base = FRONTEND_DIST.resolve()
        for candidate in (base / full_path, base / "assets" / full_path):
            resolved = candidate.resolve()
            if str(resolved).startswith(str(base)) and resolved.is_file():
                assets_dir = base / "assets"
                headers = (
                    {"Cache-Control": "public, max-age=31536000, immutable"}
                    if str(resolved).startswith(str(assets_dir))
                    else _NO_CACHE
                )
                return FileResponse(resolved, headers=headers)
        return FileResponse(_INDEX_FILE, headers=_NO_CACHE)

