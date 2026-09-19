"""Prompt templates.

Kept in one module (and mirrored as data, not string soup) so they can be
tuned per channel: small local models get tighter format constraints and fewer
instructions; cloud models get richer context and looser formatting pressure.
"""

from __future__ import annotations

import json
from typing import Literal

TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["id", "text"],
            },
        }
    },
    "required": ["translations"],
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "research_question": {"type": "string"},
        "method": {"type": "string"},
        "data_and_setup": {"type": "string"},
        "key_findings": {"type": "array", "items": {"type": "string"}},
        "novelty": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "key_numbers": {"type": "array", "items": {"type": "string"}},
        "reusable_points": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["research_question", "method", "key_findings"],
}

GLOSSARY_SCHEMA = {
    "type": "object",
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["source", "target"],
            },
        }
    },
    "required": ["terms"],
}

ASK_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "block_id": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["block_id"],
            },
        },
        "grounded": {"type": "boolean"},
    },
    "required": ["answer", "grounded"],
}

LANG_NAMES = {
    "zh": "简体中文",
    "zh-tw": "繁體中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "de": "Deutsch",
    "fr": "Français",
    "ru": "Русский",
    "es": "Español",
}

STYLE_HINT = {
    "academic": "学术通顺：符合中文科技论文表达习惯，可调整语序，但不得增删信息",
    "literal": "直译：尽量贴近原文语序与结构，便于对照阅读",
}


def _glossary_block(glossary: list[dict]) -> str:
    if not glossary:
        return "（无）"
    lines = [f"- {g['source']} → {g['target']}" for g in glossary[:120]]
    return "\n".join(lines)


def translate_prompt(
    *,
    blocks: list[dict],
    glossary: list[dict],
    context: str,
    lang: str,
    style: str,
    channel: Literal["local", "cloud"] = "cloud",
    title: str = "",
) -> list[dict[str, str]]:
    """blocks: [{id, text, type}] with placeholders already applied."""
    target = LANG_NAMES.get(lang, lang)
    payload_lines = []
    for block in blocks:
        kind = block.get("type", "text")
        payload_lines.append(f'<seg id="{block["id"]}" kind="{kind}">{block["text"]}</seg>')
    payload = "\n".join(payload_lines)

    if channel == "local":
        system = (
            f"你是学术文献翻译引擎，把英文文献片段译成{target}。"
            "严格遵守：\n"
            "1. 只输出 JSON，格式为 {\"translations\":[{\"id\":\"原文id\",\"text\":\"译文\"}]}，不要任何解释或 markdown 代码块。\n"
            "2. 每个输入 <seg> 都要有对应输出，id 必须原样复制，不得增删条目。\n"
            "3. 形如 <ph id=\"0\"/> 的占位符必须原样保留在译文的对应位置，一个都不能少、不能改。\n"
            "4. 不翻译：缩写、模型名、数据集名、单位、变量名、公司名、人名。\n"
            "5. 不增删信息，不总结，不解释。\n"
            "6. 术语必须使用给定术语表的译法。\n"
        )
    else:
        system = (
            f"你是一位资深的学术文献译者，负责把英文学术论文翻译成{target}。\n"
            f"翻译风格：{STYLE_HINT.get(style, STYLE_HINT['academic'])}。\n\n"
            "必须遵守的硬性规则：\n"
            "1. 输出严格的 JSON：{\"translations\":[{\"id\":\"...\",\"text\":\"...\"}]}，不要输出解释、前后缀或代码块标记。\n"
            "2. 输入中每个 <seg id=\"...\"> 都必须产生一条对应译文，id 原样返回；不得合并、拆分或新增条目。\n"
            "3. 形如 <ph id=\"0\"/> 的占位符代表不得翻译的内容（引用、DOI、公式、数字、图表编号）。"
            "必须在译文中按对应位置原样保留，数量与编号都不能变化。\n"
            "4. 下列内容保持原文形态：缩略语（如 CNN、BERT）、模型与数据集名称、单位、数学变量、"
            "公司与人名、参考文献编号。\n"
            "5. 忠实原文：不增加原文没有的信息，不省略原文信息，不做总结或评论。\n"
            "6. 长难句先理清主谓宾再译，避免逐词硬译；被动语态按中文学术习惯处理。\n"
            "7. 专业术语必须优先采用下方术语表给出的译法；表外术语全文保持一致。\n"
        )

    user = (
        (f"论文标题：{title}\n\n" if title else "")
        + f"【术语表】（必须遵守）\n{_glossary_block(glossary)}\n\n"
        + (f"【上文参考】（仅供理解指代，不要翻译这部分）\n{context}\n\n" if context else "")
        + f"【待翻译片段】\n{payload}\n\n"
        + f'请输出 JSON：{{"translations":[{{"id":"...","text":"..."}}]}}（目标语言：{target}）'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def summary_prompt(*, title: str, text: str, lang: str, channel: str = "cloud") -> list[dict[str, str]]:
    target = LANG_NAMES.get(lang, lang)
    system = (
        f"你是科研文献分析助手。阅读论文后，用{target}输出结构化要点。\n"
        "只输出 JSON，字段：research_question（研究问题，字符串）、method（方法与技术路线，字符串）、"
        "data_and_setup（数据与实验设置，字符串）、key_findings（主要结论，字符串数组，3-6 条，尽量带具体数字）、"
        "novelty（创新点，字符串数组）、limitations（局限，字符串数组）、"
        "key_numbers（关键数据，字符串数组）、reusable_points（对读者可复用的点，字符串数组）。\n"
        "要求：只依据给定正文，禁止编造；正文未提及的字段留空字符串或空数组；结论要具体，不要空话。"
    )
    user = f"论文标题：{title or '（未知）'}\n\n【正文】\n{text}\n\n请输出结构化 JSON。"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def glossary_prompt(*, text: str, lang: str) -> list[dict[str, str]]:
    target = LANG_NAMES.get(lang, lang)
    system = (
        "你是术语抽取工具。从学术文本中抽取需要统一译法的专业术语、缩略语、方法名、数据集名。\n"
        f"为每个术语给出{target}译法。只输出 JSON："
        '{"terms":[{"source":"...","target":"...","note":"..."}]}。\n'
        "规则：只抽取真正需要统一的术语（10-40 个），跳过常见词；缩略语要给出完整形式与译名；"
        "不要把数字、引用、公式当作术语。"
    )
    user = f"【文本】\n{text[:12000]}\n\n请输出术语表 JSON。"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


TABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "string"}},
        }
    },
    "required": ["rows"],
}


def table_prompt(
    *,
    rows: list[list[str]],
    glossary: list[dict],
    lang: str,
    channel: Literal["local", "cloud"] = "cloud",
    title: str = "",
) -> list[dict[str, str]]:
    """Translate a table while preserving its grid.

    Rows go over as JSON so the model cannot reshuffle them, and the response
    must keep exactly the same shape. Short cells (numbers, units, abbreviations)
    are expected to come back unchanged — that is correct, not a failure.
    """
    target = LANG_NAMES.get(lang, lang)
    system = (
        f"你是学术论文表格翻译器，把表格中的文字译成{target}。\n"
        "硬性规则：\n"
        "1. 只输出 JSON：{\"rows\":[[\"...\"]]}，不要解释，不要 markdown 代码块。\n"
        "2. 必须与输入的行数、每行单元格数完全一致，不得合并、拆分或增删行列。\n"
        "3. 数字、单位、缩写、变量名、模型名、数据集名保持原样（如 87.6、GB、F1、SAR 不翻译）。\n"
        "4. 形如 <ph id=\"0\"/> 的占位符必须原样保留，位置与数量不得改变。\n"
        "5. 表头与单元格都要翻译；已经是目标语言的单元格原样返回。\n"
        "6. 不添加原文没有的内容。\n"
    )
    if channel == "local":
        system += "7. 输出必须能被 JSON 解析，禁止任何多余文字。\n"
    payload = json.dumps({"rows": rows}, ensure_ascii=False)
    user = (
        (f"论文标题：{title}\n\n" if title else "")
        + f"【术语表】（必须遵守）\n{_glossary_block(glossary)}\n\n"
        + f"【待翻译表格】\n{payload}\n\n请输出 JSON：{{\"rows\":[[\"...\"]]}}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def ask_prompt(*, question: str, contexts: list[dict], lang: str, selected: str = "") -> list[dict[str, str]]:
    target = LANG_NAMES.get(lang, lang)
    context_text = "\n\n".join(
        f'<block id="{c["id"]}" page="{c.get("page", 0) + 1}">{c["text"]}</block>' for c in contexts
    )
    system = (
        "你是文献阅读助手，基于用户提供的论文片段回答问题。\n"
        "只输出 JSON：{\"answer\":\"...\",\"evidence\":[{\"block_id\":\"...\",\"quote\":\"...\"}],\"grounded\":true}。\n"
        f"要求：用{target}作答；只依据给定片段，禁止引入外部知识或编造；"
        "若片段中没有依据，grounded=false 并在 answer 中说明「文中未提及」；"
        "evidence 必须引用真实存在的 block id 与该片段中的原句。"
    )
    user = (
        (f"用户选中的文本：{selected}\n\n" if selected else "")
        + f"【论文片段】\n{context_text}\n\n【问题】{question}\n\n请输出 JSON。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
