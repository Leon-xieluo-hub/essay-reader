"""Translation pipeline: chunk → mask → LLM → repair → quality gate → cache.

The same code path serves both channels (local Ollama / cloud API); only the
provider object and prompt strictness differ. Every translated paragraph is
validated; failures are retried once with a repair hint and, if still bad, are
stored with quality="suspect" so the UI can offer a one-click cloud retry
instead of silently showing a bad translation.
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable, Optional

from app import db
from app.config import settings
from app.providers import (
    ProviderError,
    ProviderUnavailable,
    estimate_tokens,
    get_provider,
)
from app.schemas import Block
from app.services import prompts
from app.services.protect import PLACEHOLDER_RE, mask, unmask, validate

ProgressCb = Optional[Callable[[int, int, str], Awaitable[None]]]

TRANSLATABLE = {"text", "heading", "caption", "reference", "footnote", "table"}
SKIP_TYPES = {"header", "footer"}
# A block needs at least one letter (Latin or CJK) outside its protected
# fragments to be worth a model call; "5. 6. 7. 8." and URL-only lines are not.
_LETTER_RE = re.compile(r"[A-Za-z\u4e00-\u9fff]")


def _table_plain_text(block: Block) -> str:
    """Flatten a table so the generic machinery (token budget, cache) can size it."""
    if not block.table_rows:
        return block.text
    return "\n".join(" | ".join(cell for cell in row) for row in block.table_rows)


def select_blocks(blocks: list[Block], block_ids: Optional[list[str]] = None) -> list[Block]:
    wanted = set(block_ids) if block_ids else None
    out: list[Block] = []
    for block in blocks:
        if wanted is not None and block.id not in wanted:
            continue
        if block.type in SKIP_TYPES or block.type not in TRANSLATABLE:
            continue
        if block.type == "table":
            # a table is translated as a grid, not as prose; keep only real tables
            if not block.table_rows or len(block.table_rows) < 2:
                continue
            if len(_table_plain_text(block).strip()) < 2:
                continue
            out.append(block)
            continue
        if len(block.text.strip()) < 2:
            continue
        # Anything the masker would eat (citations, numbers, dates, URLs) can be
        # the whole block: a numbered list or a bare access URL carries nothing
        # to translate, and asking the model anyway produced "5。6。7。…".
        residual = PLACEHOLDER_RE.sub("", mask(block.text).text)
        if not _LETTER_RE.search(residual):
            continue
        out.append(block)
    return out


def chunk_blocks(blocks: list[Block], budget: Optional[int] = None) -> list[list[Block]]:
    """Group blocks into chunks that respect the token budget.

    Tables are kept out of text chunks: they are translated separately as a grid
    so the model can never reshuffle their rows.
    """
    limit = budget or settings.chunk_token_budget
    chunks: list[list[Block]] = []
    current: list[Block] = []
    used = 0
    for block in blocks:
        if block.type == "table":
            if current:
                chunks.append(current)
                current = []
                used = 0
            chunks.append([block])
            continue
        cost = estimate_tokens(block.text) + 24
        if current and used + cost > limit:
            chunks.append(current)
            current = []
            used = 0
        current.append(block)
        used += cost
    if current:
        chunks.append(current)
    return chunks


async def _translate_chunk(
    *,
    chunk: list[Block],
    provider_key: str,
    lang: str,
    style: str,
    glossary: list[dict],
    context: str,
    title: str,
    repair_hint: str = "",
) -> tuple[dict[str, str], list[str], int, int]:
    provider = get_provider(provider_key)
    masked_pairs = [(block, mask(block.text)) for block in chunk]
    payload = [
        {"id": block.id, "text": masked.text, "type": block.type}
        for block, masked in masked_pairs
    ]
    messages = prompts.translate_prompt(
        blocks=payload,
        glossary=glossary,
        context=context,
        lang=lang,
        style=style,
        channel="local" if provider_key == "local" else "cloud",
        title=title,
    )
    if repair_hint:
        messages[-1]["content"] += f"\n\n【上次输出的问题，请修正】{repair_hint}"

    data = await provider.chat_json(messages, schema=prompts.TRANSLATE_SCHEMA)
    usage = provider.last_usage
    items = data.get("translations") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ProviderError("模型输出缺少 translations 数组")

    raw_map: dict[str, str] = {}
    for item in items:
        if isinstance(item, dict) and "id" in item:
            raw_map[str(item["id"])] = str(item.get("text", ""))

    results: dict[str, str] = {}
    problems: list[str] = []
    for block, masked in masked_pairs:
        translated = raw_map.get(block.id, "")
        if not translated:
            problems.append(f"{block.id}: 缺少译文")
            results[block.id] = ""
            continue
        restored, issues = unmask(translated, masked)
        for problem in validate(block.text, masked, restored, target_lang=lang) + issues:
            problems.append(f"{block.id}: {problem}")
        results[block.id] = restored
    return results, problems, usage.tokens_in, usage.tokens_out


async def _translate_table(
    *,
    block: Block,
    provider_key: str,
    lang: str,
    glossary: list[dict],
    title: str,
) -> tuple[list[list[str]] | None, str, int, int]:
    """Translate every cell while preserving the grid.

    Cell text is masked exactly like prose (formulas, numbers, citations), the
    rows go over as JSON, and the reply is rejected unless it has the identical
    shape — a table whose rows shifted would silently mislabel data.
    """
    rows = block.table_rows or []
    if not rows:
        return None, "failed", 0, 0
    provider = get_provider(provider_key)
    masked_rows: list[list[str]] = []
    masks: list[list] = []
    for row in rows:
        masked_row: list[str] = []
        mask_row: list = []
        for cell in row:
            masked = mask(cell or "")
            masked_row.append(masked.text)
            mask_row.append(masked)
        masked_rows.append(masked_row)
        masks.append(mask_row)

    data = await provider.chat_json(
        prompts.table_prompt(
            rows=masked_rows,
            glossary=glossary,
            lang=lang,
            channel="local" if provider_key == "local" else "cloud",
            title=title,
        ),
        schema=prompts.TABLE_SCHEMA,
    )
    tokens_in = provider.last_usage.tokens_in
    tokens_out = provider.last_usage.tokens_out
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise ProviderError("表格翻译输出缺少 rows 数组")
    returned = data["rows"]

    width = len(rows[0])
    dimension_ok = len(returned) == len(rows) and all(
        isinstance(r, list) and len(r) == len(rows[i]) for i, r in enumerate(returned)
    )
    if not dimension_ok:
        return None, "failed", tokens_in, tokens_out

    restored_rows: list[list[str]] = []
    untouched = empty = 0
    for source_row, result_row, mask_row in zip(rows, returned, masks):
        out_row: list[str] = []
        for source, value, masked in zip(source_row, result_row, mask_row):
            text = str(value or "").strip()
            if not text:
                out_row.append("")
                empty += 1
                continue
            text, _issues = unmask(text, masked)
            out_row.append(text)
            if text.strip() == (source or "").strip():
                untouched += 1
        restored_rows.append(out_row)

    # quality: row-shape integrity first, then a coarse completeness signal.
    # A two-column table often keeps its right column untranslated (numbers,
    # abbreviations), so "untouched" only becomes suspicious in wide tables.
    problems = 0
    if not dimension_ok:
        problems += 10
    if empty and empty > len(rows):
        problems += 3
    if width >= 3 and untouched > len(rows) * width * 0.3:
        problems += 3
    quality = "suspect" if problems >= 3 else "ok"
    return restored_rows, quality, tokens_in, tokens_out


def _context_for(blocks: list[Block], index: int, count: int) -> str:
    if count <= 0:
        return ""
    start = max(0, index - count)
    pieces = [b.text.strip() for b in blocks[start:index] if b.text.strip()]
    return "\n".join(pieces)[-1500:]


async def translate_document(
    *,
    doc_id: str,
    provider_key: str,
    lang: str = "zh",
    style: str = "academic",
    block_ids: Optional[list[str]] = None,
    force: bool = False,
    progress: ProgressCb = None,
) -> dict:
    if provider_key == "off":
        raise ProviderUnavailable("AI 功能已关闭：请启用本地模型或配置云端 API")

    provider = get_provider(provider_key)
    all_blocks = db.get_blocks(doc_id)
    targets = select_blocks(all_blocks, block_ids)
    if not targets:
        return {"translated": 0, "failed": 0, "skipped": 0, "quality": "ok"}

    existing = db.get_translations(doc_id, lang)
    if force:
        pending = targets
        skipped = 0
    else:
        pending = [
            b
            for b in targets
            if not any(
                t["provider"] == provider_key
                and t["model"] == provider.model
                and t["quality"] != "failed"
                and (t["text"] or "").strip()
                for t in existing.get(b.id, [])
            )
        ]
        skipped = len(targets) - len(pending)

    if not pending:
        if progress:
            await progress(len(targets), len(targets), "全部段落已有译文，直接复用缓存")
        return {"translated": 0, "failed": 0, "skipped": skipped, "quality": "ok"}

    glossary = [g.model_dump() for g in db.get_glossary(doc_id)]
    meta = db.get_document(doc_id) or {}
    title = meta.get("title") or meta.get("filename") or ""

    context_source = [b for b in all_blocks if b.type in ("text", "heading") and b.text.strip()]
    index_of = {b.id: i for i, b in enumerate(context_source)}

    chunks = chunk_blocks(pending)
    completed = skipped
    failed = 0
    suspect = 0
    tokens_in_total = 0
    tokens_out_total = 0
    budget_used = 0
    consecutive_failures = 0

    for chunk in chunks:
        # -- tables: translated as a grid, never as prose -------------------
        if len(chunk) == 1 and chunk[0].type == "table":
            block = chunk[0]
            try:
                rows, quality, t_in, t_out = await _translate_table(
                    block=block,
                    provider_key=provider_key,
                    lang=lang,
                    glossary=glossary,
                    title=title,
                )
            except ProviderUnavailable:
                raise
            except Exception as exc:
                db.upsert_translation(
                    block_id=block.id,
                    doc_id=doc_id,
                    lang=lang,
                    provider=provider_key,
                    model=provider.model,
                    text="",
                    quality="failed",
                    attempts=1,
                )
                failed += 1
                completed += 1
                consecutive_failures += 1
                if progress:
                    await progress(completed, len(targets), f"表格翻译失败：{exc}")
                if consecutive_failures >= 2:
                    raise ProviderUnavailable(
                        f"{provider_key} 通道连续 {consecutive_failures} 次调用失败，已停止：{exc}"
                    )
                continue
            tokens_in_total += t_in
            tokens_out_total += t_out
            consecutive_failures = 0
            if rows:
                block.table_rows_translated = rows
                db.insert_blocks([block])
                quality = "ok"
            else:
                quality = "failed"
                failed += 1
            db.upsert_translation(
                block_id=block.id,
                doc_id=doc_id,
                lang=lang,
                provider=provider_key,
                model=provider.model,
                text="[表格]" if rows else "",
                quality=quality,
                attempts=1,
            )
            completed += 1
            if progress:
                await progress(completed, len(targets), f"已翻译 {completed}/{len(targets)} 段（含表格）")
            continue

        anchor = index_of.get(chunk[0].id, 0) if context_source else 0
        context = _context_for(context_source, anchor, settings.context_paragraphs)

        try:
            results, problems, tokens_in, tokens_out = await _translate_chunk(
                chunk=chunk,
                provider_key=provider_key,
                lang=lang,
                style=style,
                glossary=glossary,
                context=context,
                title=title,
            )
        except ProviderUnavailable:
            raise
        except Exception as exc:
            for block in chunk:
                db.upsert_translation(
                    block_id=block.id,
                    doc_id=doc_id,
                    lang=lang,
                    provider=provider_key,
                    model=provider.model,
                    text="",
                    quality="failed",
                    attempts=1,
                )
            failed += len(chunk)
            completed += len(chunk)
            consecutive_failures += 1
            if progress:
                await progress(completed, len(targets), f"翻译失败：{exc}")
            # Fail fast when the channel itself looks broken (service down, key
            # rejected, model missing) instead of grinding through every chunk.
            if consecutive_failures >= 2 and failed >= len(chunk) * 2:
                raise ProviderUnavailable(
                    f"{provider_key} 通道连续 {consecutive_failures} 次调用失败，已停止：{exc}"
                )
            continue

        tokens_in_total += tokens_in
        tokens_out_total += tokens_out
        consecutive_failures = 0

        bad_ids = {p.split(":", 1)[0] for p in problems if ":" in p}
        if bad_ids and settings.quality_retry_limit > 0:
            retry_blocks = [b for b in chunk if b.id in bad_ids]
            try:
                retry_results, retry_problems, r_in, r_out = await _translate_chunk(
                    chunk=retry_blocks,
                    provider_key=provider_key,
                    lang=lang,
                    style=style,
                    glossary=glossary,
                    context=context,
                    title=title,
                    repair_hint="；".join(problems[:4]),
                )
                tokens_in_total += r_in
                tokens_out_total += r_out
                for block_id, text in retry_results.items():
                    if text.strip():
                        results[block_id] = text
                problems = [p for p in problems if p.split(":", 1)[0] not in retry_results]
                problems += [p for p in retry_problems if p.split(":", 1)[0] in retry_results]
            except Exception:
                pass

        for block in chunk:
            text = results.get(block.id, "")
            block_problems = [p for p in problems if p.startswith(f"{block.id}:")]
            if not text.strip():
                quality = "failed"
                failed += 1
            elif block_problems:
                quality = "suspect"
                suspect += 1
            else:
                quality = "ok"
            db.upsert_translation(
                block_id=block.id,
                doc_id=doc_id,
                lang=lang,
                provider=provider_key,
                model=provider.model,
                text=text,
                quality=quality,
                attempts=2 if block.id in bad_ids else 1,
            )
            completed += 1
        if progress:
            await progress(completed, len(targets), f"已翻译 {completed}/{len(targets)} 段")

        budget_used += tokens_in + tokens_out
        if settings.token_budget_per_doc and budget_used > settings.token_budget_per_doc:
            if progress:
                await progress(completed, len(targets), "已达到本篇 token 预算上限，停止翻译")
            break

    db.record_usage(
        provider=provider_key,
        model=provider.model,
        tokens_in=tokens_in_total,
        tokens_out=tokens_out_total,
        seconds=provider.last_usage.seconds,
        kind="translate",
    )
    return {
        "translated": max(0, completed - skipped - failed),
        "failed": failed,
        "suspect": suspect,
        "skipped": skipped,
        "total": len(targets),
        "done": completed,
        "tokens_in": tokens_in_total,
        "tokens_out": tokens_out_total,
        "provider": provider_key,
        "model": provider.model,
        "lang": lang,
    }


async def translate_single_block(
    *,
    doc_id: str,
    block_id: str,
    provider_key: str,
    lang: str = "zh",
    style: str = "academic",
) -> dict:
    return await translate_document(
        doc_id=doc_id,
        provider_key=provider_key,
        lang=lang,
        style=style,
        block_ids=[block_id],
        force=True,
    )


def _candidate_terms(blocks: list[Block], limit: int = 80) -> list[str]:
    """Cheap acronym/multiword extraction used to seed the glossary prompt."""
    counts: dict[str, int] = {}
    acronym = re.compile(r"\b[A-Z][A-Za-z]*[A-Z][A-Za-z0-9\-]{1,12}\b")
    multiword = re.compile(r"\b(?:[A-Z][a-z]{3,}\s){1,2}(?:[a-z]{4,}|[A-Z][a-z]{3,})\b")
    for block in blocks:
        if block.type not in ("text", "heading"):
            continue
        for match in acronym.finditer(block.text):
            token = match.group(0)
            if token.upper() in {"THE", "AND", "FOR", "WITH"}:
                continue
            counts[token] = counts.get(token, 0) + 1
        for match in multiword.finditer(block.text):
            token = match.group(0).strip()
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [term for term, freq in ranked if freq >= 2][:limit]


async def build_glossary(
    doc_id: str, provider_key: str, lang: str = "zh", max_terms: int = 30
) -> list[dict]:
    """Extract terms once, persist them, reuse for every later translation."""
    if provider_key == "off":
        return []
    blocks = db.get_blocks(doc_id)
    text_blocks = [b for b in blocks if b.type in ("text", "heading") and len(b.text) > 40]
    if not text_blocks:
        return []
    candidates = _candidate_terms(blocks)
    sample = "\n".join(b.text for b in text_blocks[:40])[:12000]
    if candidates:
        sample = "【候选术语】\n" + ", ".join(candidates) + "\n\n" + sample
    provider = get_provider(provider_key)
    try:
        data = await provider.chat_json(
            prompts.glossary_prompt(text=sample, lang=lang), schema=prompts.GLOSSARY_SCHEMA
        )
    except Exception:
        return [g.model_dump() for g in db.get_glossary(doc_id)]
    terms = data.get("terms") if isinstance(data, dict) else None
    if isinstance(terms, list):
        for term in terms[:max_terms]:
            if not isinstance(term, dict):
                continue
            source = str(term.get("source", "")).strip()
            target = str(term.get("target", "")).strip()
            if 1 < len(source) <= 80 and target:
                db.upsert_glossary(doc_id, source, target, str(term.get("note", ""))[:200])
    db.record_usage(
        provider=provider_key,
        model=provider.model,
        tokens_in=provider.last_usage.tokens_in,
        tokens_out=provider.last_usage.tokens_out,
        seconds=provider.last_usage.seconds,
        kind="glossary",
    )
    return [g.model_dump() for g in db.get_glossary(doc_id)]
