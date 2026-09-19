"""Structured-content protection for translation.

The single biggest source of translation damage in academic PDFs is the model
rewriting things it must not touch: citations, DOIs, URLs, math. We therefore
mask them behind opaque placeholders before the LLM sees the text and restore
them afterwards, then verify the counts survived the round trip.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Order matters: DOIs before bare URLs, URLs before bare numbers.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("doi", re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")),
    ("url", re.compile(r"https?://[^\s<>\)\]]+")),
    ("cite", re.compile(r"\[\s*\d{1,3}(?:\s*[-,–]\s*\d{1,3})*\s*\]")),
    ("cite", re.compile(r"\[[A-Za-z][A-Za-z .&'\-]{1,40},\s*(?:19|20)\d{2}[a-z]?\]")),
    ("eqref", re.compile(r"\b(?:Eq\.?|Equation|Eqs\.?)\s*\(?\d{1,3}\)?")),
    ("figref", re.compile(r"\b(?:Fig\.?|Figure|Tab\.?|Table|Sec\.?|Section|Alg\.?|Algorithm)\s*\.?\s*\d{1,3}[a-zA-Z]?")),
    ("math", re.compile(r"\$[^$\n]{1,120}\$")),
    ("math", re.compile(r"\\\([^\n]{1,120}?\\\)")),
    ("cite", re.compile(r"\([A-Z][A-Za-z\-']+(?:\s+(?:et al\.?|and|&)\s+[A-Z][A-Za-z\-']*)?,\s*(?:19|20)\d{2}[a-z]?\)")),
    # Dates must survive verbatim: a model asked to translate "1 February 2020"
    # happily produces "1 年 2020 月", which is worse than leaving it alone.
    ("date", re.compile(r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+\d{4}\b")),
    ("date", re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b")),
    ("date", re.compile(r"\b(?:19|20)\d{2}-\d{1,2}-\d{1,2}\b")),
    ("date", re.compile(r"\b(?:19|20)\d{2}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?")),
    # Short digit+letter tokens ("3D", "2D", "5G") are protected as a whole.
    # Masking only the digit split them into `<ph id="0"/>D`, and models that
    # reflowed the tag left stray digits in the translated sentence.
    ("num", re.compile(r"(?<![\w.])\d{1,2}[A-Z]{1,3}(?![\w])")),
    # A trailing guard keeps the rule out of alphanumeric tokens such as
    # "3DPhenoMVS"; there the model must see the token intact.
    ("num", re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?:\s?(?:%|‰|×10\^?-?\d+))?(?![\w])")),
]

PLACEHOLDER_OPEN = "<ph"
PLACEHOLDER_RE = re.compile(r"<ph\s+id=\"(\d+)\"\s*/>")


@dataclass
class Masked:
    text: str
    tokens: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for kind in self.kinds:
            out[kind] = out.get(kind, 0) + 1
        return out


def mask(text: str) -> Masked:
    """Replace protected fragments with `<ph id="n"/>` placeholders."""
    if not text:
        return Masked(text="")
    spans: list[tuple[int, int, str, str]] = []
    for kind, pattern in PATTERNS:
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end(), kind, match.group(0)))
    # keep outermost, non-overlapping matches; longer match wins on ties
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    chosen: list[tuple[int, int, str, str]] = []
    cursor = -1
    for span in spans:
        if span[0] >= cursor:
            chosen.append(span)
            cursor = span[1]
    if not chosen:
        return Masked(text=text)
    pieces: list[str] = []
    tokens: list[str] = []
    kinds: list[str] = []
    prev = 0
    for start, end, kind, raw in chosen:
        pieces.append(text[prev:start])
        index = len(tokens)
        pieces.append(f'<ph id="{index}"/>')
        tokens.append(raw)
        kinds.append(kind)
        prev = end
    pieces.append(text[prev:])
    return Masked(text="".join(pieces), tokens=tokens, kinds=kinds)


def unmask(translated: str, masked: Masked) -> tuple[str, list[str]]:
    """Restore placeholders; report problems instead of failing silently."""
    issues: list[str] = []
    seen: set[int] = set()

    def restore(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        if idx >= len(masked.tokens):
            issues.append(f"未知占位符 {idx}")
            return match.group(0)
        seen.add(idx)
        return masked.tokens[idx]

    text = PLACEHOLDER_RE.sub(restore, translated)
    missing = [i for i in range(len(masked.tokens)) if i not in seen]
    for idx in missing:
        issues.append(f"占位符 {idx}（{masked.tokens[idx]}）在译文中丢失，已回填原文")
        text = text + " " + masked.tokens[idx] if idx == len(masked.tokens) - 1 else text
    # model sometimes degrades the tag (e.g. <ph id=0>) — clean leftovers
    leftovers = re.findall(r"</?ph[^>]*>", text)
    if leftovers:
        issues.append(f"残留占位符标记 {len(leftovers)} 处，已清理")
        text = re.sub(r"</?ph[^>]*>", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip(), issues


def validate(source: str, masked: Masked, translated: str, target_lang: str = "zh") -> list[str]:
    """Post-translation checks. Returns a list of problems (empty = pass).

    Structural markers like `Fig. 3` legitimately become `图 3` in Chinese, so
    those count checks only apply when the target language keeps the same
    surface form (an English target). Citations, numbers and lengths are
    language-independent and always checked.
    """
    problems: list[str] = []
    if not translated.strip():
        return ["译文为空"]
    src_counts = masked.counts
    tgt = mask(translated)
    tgt_counts = tgt.counts
    keep_surface = not target_lang.lower().startswith("zh")
    for kind, expected in src_counts.items():
        if kind in ("num", "math"):
            continue  # already protected/restored; re-masking would double count
        if kind in ("figref", "eqref") and not keep_surface:
            continue
        got = tgt_counts.get(kind, 0)
        if got < expected:
            problems.append(f"{kind} 数量不一致（原文 {expected}，译文 {got}）")
    # numbers must survive. Only digits the model is actually responsible for
    # count: placeholder ids like `<ph id="7"/>` are ours, not the paper's, and
    # counting them made a nine-placeholder paragraph look like nine numbers.
    src_nums = re.findall(r"\d+(?:\.\d+)?", PLACEHOLDER_RE.sub("", masked.text))
    tgt_nums = re.findall(r"\d+(?:\.\d+)?", PLACEHOLDER_RE.sub("", tgt.text))
    if src_nums and len(tgt_nums) < len(src_nums):
        problems.append(f"数字疑似丢失（原文 {len(src_nums)}，译文 {len(tgt_nums)}）")
    # Length ratio is only meaningful for running text, and the bound has to be
    # loose: technical Chinese runs at roughly 0.25-0.4 of the English character
    # count, so a floor near 1.0 would flag every correct translation (it did).
    if len(masked.text) >= 120:
        ratio = len(translated) / max(1, len(masked.text))
        if ratio < 0.12:
            problems.append(f"译文字数异常偏少（比例 {ratio:.2f}），疑似漏译")
        if ratio > 4.0:
            problems.append(f"译文字数异常偏多（比例 {ratio:.2f}），疑似扩写/幻觉")
    if re.search(r"[\u4e00-\u9fff]", translated) is None and len(masked.text) > 60:
        # only a real problem when the text is long and clearly untranslated
        src_cjk = len(re.findall(r"[\u4e00-\u9fff]", masked.text))
        if src_cjk == 0:
            problems.append("译文未包含目标语言内容，疑似未翻译")
    if translated.count("<ph") > len(masked.tokens):
        problems.append("占位符重复出现")
    return problems


def looks_like_heading(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and len(stripped) < 120 and not stripped.endswith((".", "。", ";", "；"))
