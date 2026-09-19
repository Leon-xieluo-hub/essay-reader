"""Structured summarization + retrieval-grounded Q&A over one document."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional

from app import db
from app.providers import ProviderError, ProviderUnavailable, estimate_tokens, get_provider
from app.schemas import Block
from app.services import prompts

SUMMARY_TEXT_BUDGET = 9000  # tokens handed to the summarizer


def _summary_source(blocks: list[Block]) -> str:
    """Headings + opening + closing + captions/tables, within a token budget."""
    useful = [
        b
        for b in blocks
        if b.text.strip() and b.type in ("heading", "text", "caption", "table", "reference")
    ]
    if not useful:
        return ""
    head = [b for b in useful if b.type == "heading"]
    body = [b for b in useful if b.type == "text"]
    tail = [b for b in useful if b.type in ("caption", "table", "reference")]

    picked: list[Block] = list(head)
    used = sum(estimate_tokens(b.text) for b in picked)
    split = max(1, int(len(body) * 0.6))
    for group in (body[:split], tail, body[split:]):
        for block in group:
            cost = estimate_tokens(block.text)
            if used + cost > SUMMARY_TEXT_BUDGET:
                continue
            picked.append(block)
            used += cost
    picked.sort(key=lambda b: b.order)
    return "\n".join(f"[{b.type}] {b.text.strip()}" for b in picked)


def _render_summary(data: dict, lang: str) -> str:
    def as_list(value) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    labels = {
        "zh": {
            "research_question": "研究问题",
            "method": "方法与技术路线",
            "data_and_setup": "数据与实验设置",
            "key_findings": "主要结论",
            "novelty": "创新点",
            "limitations": "局限",
            "key_numbers": "关键数据",
            "reusable_points": "可复用之处",
        }
    }.get(lang, {})

    def label(key: str, fallback: str) -> str:
        return labels.get(key, fallback) if labels else fallback

    lines: list[str] = []
    for key, fallback in (
        ("research_question", "Research question"),
        ("method", "Method"),
        ("data_and_setup", "Data & setup"),
    ):
        value = str(data.get(key) or "").strip()
        if value:
            lines.append(f"## {label(key, fallback)}\n{value}\n")
    for key, fallback in (
        ("key_findings", "Key findings"),
        ("novelty", "Novelty"),
        ("limitations", "Limitations"),
        ("key_numbers", "Key numbers"),
        ("reusable_points", "Reusable points"),
    ):
        items = as_list(data.get(key))
        if items:
            body = "\n".join(f"- {item}" for item in items)
            lines.append(f"## {label(key, fallback)}\n{body}\n")
    return "\n".join(lines).strip()


async def summarize_document(
    *, doc_id: str, provider_key: str, lang: str = "zh", force: bool = False
) -> dict:
    if provider_key == "off":
        raise ProviderUnavailable("AI 功能已关闭：请启用本地模型或配置云端 API")
    provider = get_provider(provider_key)
    cached = db.get_summary(doc_id, lang)
    if cached and not force and cached["provider"] == provider_key and cached["model"] == provider.model:
        return {
            "content": cached["content"],
            "provider": cached["provider"],
            "model": cached["model"],
            "cached": True,
        }

    blocks = db.get_blocks(doc_id)
    source = _summary_source(blocks)
    if not source:
        return {
            "content": "",
            "provider": provider_key,
            "model": provider.model,
            "error": "文档没有可用于总结的正文",
        }

    meta = db.get_document(doc_id) or {}
    data = await provider.chat_json(
        prompts.summary_prompt(
            title=meta.get("title") or meta.get("filename", ""),
            text=source,
            lang=lang,
            channel=provider_key,
        ),
        schema=prompts.SUMMARY_SCHEMA,
    )
    content = _render_summary(data if isinstance(data, dict) else {}, lang)
    db.save_summary(
        doc_id=doc_id, lang=lang, provider=provider_key, model=provider.model, content=content
    )
    db.record_usage(
        provider=provider_key,
        model=provider.model,
        tokens_in=provider.last_usage.tokens_in,
        tokens_out=provider.last_usage.tokens_out,
        seconds=provider.last_usage.seconds,
        kind="summary",
    )
    return {
        "content": content,
        "provider": provider_key,
        "model": provider.model,
        "cached": False,
        "tokens_in": provider.last_usage.tokens_in,
        "tokens_out": provider.last_usage.tokens_out,
    }


# ------------------------------------------------------------------------ QA

_WORD = re.compile(r"[A-Za-z][A-Za-z\-]{1,}|\d+(?:\.\d+)?|[\u4e00-\u9fff]+")


def _tokens(text: str) -> list[str]:
    """Tokens for retrieval, with CJK handled as character bigrams.

    Splitting Chinese into 4-character chunks looks reasonable but is useless for
    a Chinese question asked against an English paper: no chunk ever matches, so
    retrieval returns nothing and the model sees no evidence at all — which shows
    up as a spurious "文中未提及". Overlapping bigrams give partial matches on
    numbers, acronyms and table/figure references, which is what actually anchors
    the evidence.
    """
    tokens: list[str] = []
    for match in _WORD.findall(text):
        if match[0].isascii():
            tokens.append(match.lower())
            continue
        chars = list(match)
        if len(chars) == 1:
            tokens.append(chars[0])
            continue
        tokens.extend("".join(chars[i : i + 2]) for i in range(len(chars) - 1))
    return tokens


def _retrieval_text(block: Block, translations: dict[str, list[dict]], provider_key: str) -> str:
    """Text used for matching: the translated body when we have it.

    A question is usually asked in the reader's own language, so matching it
    against the original English text finds nothing (a Chinese question simply
    shares no tokens with English prose). The translated paragraphs are the
    corpus actually written in the question's language; the original remains the
    fallback and is what gets sent to the model as evidence.
    """
    variants = translations.get(block.id, [])
    for variant in variants:
        if variant.get("provider") == provider_key and (variant.get("text") or "").strip():
            return variant["text"]
    for variant in variants:
        if (variant.get("text") or "").strip():
            return variant["text"]
    return block.text


def _bm25_rank(
    blocks: list[Block],
    query: str,
    top_k: int,
    translations: Optional[dict[str, list[dict]]] = None,
    provider_key: str = "",
) -> list[Block]:
    """Pure-CPU retrieval so a local setup never fights the GPU for VRAM."""
    variants = translations or {}
    docs = [
        (b, _tokens(_retrieval_text(b, variants, provider_key)))
        for b in blocks
        if b.text.strip() and b.type in ("text", "heading", "caption", "table")
    ]
    if not docs:
        return []
    q_terms = _tokens(query)
    if not q_terms:
        return [b for b, _ in docs[:top_k]]
    avg_len = sum(len(t) for _, t in docs) / max(1, len(docs))
    df: Counter[str] = Counter()
    for _, tokens in docs:
        for term in set(tokens):
            df[term] += 1
    n = len(docs)
    k1, b_param = 1.4, 0.72
    scored: list[tuple[float, Block]] = []
    for block, tokens in docs:
        tf = Counter(tokens)
        length = len(tokens) or 1
        score = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += (
                idf
                * (tf[term] * (k1 + 1))
                / (tf[term] + k1 * (1 - b_param + b_param * length / avg_len))
            )
        if score > 0:
            scored.append((score, block))
    scored.sort(key=lambda pair: -pair[0])
    return [block for _, block in scored[:top_k]]


async def ask_document(
    *,
    doc_id: str,
    question: str,
    provider_key: str,
    lang: str = "zh",
    block_ids: Optional[list[str]] = None,
    top_k: int = 6,
) -> dict:
    if provider_key == "off":
        raise ProviderUnavailable("AI 功能已关闭：请启用本地模型或配置云端 API")
    blocks = db.get_blocks(doc_id)
    if not blocks:
        return {"answer": "文档尚未解析。", "evidence": [], "grounded": False}

    by_id = {b.id: b for b in blocks}
    translations = db.get_translations(doc_id, lang)
    contexts: list[Block] = []
    if block_ids:
        for block_id in block_ids:
            block = by_id.get(block_id)
            if block:
                contexts.append(block)
    selected_text = contexts[0].text[:400] if contexts else ""
    # The abstract is where authors state the contribution, results and scope, so
    # it belongs in the context of (almost) any question. Retrieval alone often
    # misses it because a short abstract shares few tokens with the question.
    abstract: list[Block] = []
    for block in blocks:
        if block.page > 1 or block.type not in ("text", "heading"):
            continue
        text = _retrieval_text(block, translations, provider_key)
        if re.search(r"(abstract|摘要)", text[:40], re.I) or (
            block.type == "text" and len(text) > 400
        ):
            abstract.append(block)
        if len(abstract) >= 2:
            break
    contexts.extend(abstract)
    if len(contexts) < top_k:
        ranked = _bm25_rank(blocks, question, top_k, translations, provider_key)
        seen = {b.id for b in contexts}
        contexts.extend(b for b in ranked if b.id not in seen)
    contexts = contexts[: max(top_k + 2, 6)]

    provider = get_provider(provider_key)
    data = await provider.chat_json(
        prompts.ask_prompt(
            question=question,
            contexts=[
                {"id": b.id, "page": b.page, "text": b.text[:1800]} for b in contexts
            ],
            lang=lang,
            selected=selected_text,
        ),
        schema=prompts.ASK_SCHEMA,
    )
    if not isinstance(data, dict):
        raise ProviderError("问答返回格式异常")

    answer = str(data.get("answer") or "").strip()
    evidence_raw = data.get("evidence") or []
    evidence: list[dict] = []
    if isinstance(evidence_raw, list):
        for item in evidence_raw:
            if not isinstance(item, dict):
                continue
            block_id = str(item.get("block_id", ""))
            block = by_id.get(block_id)
            if not block:
                continue
            evidence.append(
                {
                    "block_id": block_id,
                    "page": block.page,
                    "quote": str(item.get("quote") or block.text[:160]),
                }
            )
    if not evidence:
        evidence = [
            {"block_id": b.id, "page": b.page, "quote": b.text[:160]} for b in contexts[:3]
        ]
    db.record_usage(
        provider=provider_key,
        model=provider.model,
        tokens_in=provider.last_usage.tokens_in,
        tokens_out=provider.last_usage.tokens_out,
        seconds=provider.last_usage.seconds,
        kind="ask",
    )
    return {
        "answer": answer,
        "evidence": evidence,
        "grounded": bool(data.get("grounded", bool(answer))),
        "provider": provider_key,
        "model": provider.model,
    }
