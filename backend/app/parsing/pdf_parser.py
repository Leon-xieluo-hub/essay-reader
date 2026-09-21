"""PDF → Document IR parser.

Pipeline per page:
  1. rebuild lines/paragraphs from the text layer (with font metrics)
  2. detect column layout, assign reading order
  3. classify blocks (heading / caption / footnote / reference / formula-ish)
  4. cut figures by bbox and rebuild tables as structured HTML
  5. emit a ParseReport so the UI can show parse quality honestly

Design notes:
  * Every block keeps its page + bbox so the original PDF view stays an exact
    fallback for anything the parser renders imperfectly.
  * Nothing here needs the network, so parsing works fully offline.
"""

from __future__ import annotations

import copy
import hashlib
import html
import re
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import pymupdf

from app.config import ASSET_DIR, settings
from app.parsing.ocr import image_coverage, ocr_page, ocr_status
from app.schemas import BBox, Block, PageInfo, ParseReport

# ---------------------------------------------------------------- text helpers

_HYPHEN_END = re.compile(r"(\w)[-\u2010\u2011]$")
_CID_GARBAGE = re.compile(r"\(cid:\d+\)")
_MULTISPACE = re.compile(r"[ \t]{2,}")
_GARBAGE_CHARS = re.compile(r"[\ufffd\u25a1\u25a0]")
_FORMULA_HINT = re.compile(
    r"(?:[=≈≤≥∑∫√±×÷·^_]\s*[\w\\])|(?:\\[a-zA-Z]+\{)|\b(?:where|s\.t\.)\b.*[=<>]"
)
_REF_START = re.compile(r"^\s*(\[?\d{1,3}\]?[.)]?\s|[A-Z][a-z]+,\s+[A-Z]\.)")
_CAPTION_START = re.compile(
    r"^\s*(figure|fig\.?|table|tab\.?|scheme|algorithm|listing)\s*\d+", re.I
)
# A numbered section heading: "1 Introduction", "2.1. Pipeline", "3.1.2. Foo".
# The leading number must be small and followed by a dotted/multi-level or short
# title — otherwise body prose that merely starts with a number ("100 images
# were taken…") gets swallowed as a heading.
_SECTION_NUM = re.compile(r"^\s*\d{1,2}(?:\.\d{1,2})*\.?\s+\S")
_SECTION_NUM_BARE = re.compile(r"^\s*\d{1,2}[.)]?\s+[A-Z]\S")
_ROMAN_SECTION = re.compile(r"^\s*[IVX]{1,4}[.)]?\s+\S")
# Running heads / folios such as "5 of 17", "Page 5 of 17", "5/17".
_PAGE_NUMBER = re.compile(
    r"^\s*(?:page\s+)?\d{1,4}\s*(?:of|/)\s*\d{1,4}\s*$", re.I
)
_FOLIO_ONLY = re.compile(r"^\s*\d{1,4}\s*$")
# Front-matter / sidebar labels such as "Citation:", "Article Info", "Funding:".
# Publishers put these in a narrow rail next to the abstract, and their lines
# can overlap the body column horizontally, so geometry alone cannot separate
# them — the labels are the reliable signal.
_META_LABEL = re.compile(
    r"^\s*(article\s+info|abstract|keywords?|citation|cite\s+this\s+article|"
    r"funding|funding\s+information|acknowledg(?:e?ments?)|author\s+contributions?|"
    r"conflicts?\s+of\s+interest|data\s+availability|ethics?\s+statement|"
    r"informed\s+consent|abbreviations?|supplementary\s+material|"
    r"correspondence|academic\s+editor|received|revised|accepted|published|"
    r"doi|issn|copyright|license|publisher'?s?\s+note|institutional\s+review|"
    r"highlights?|graphical\s+abstract|editor)\s*:?\s*$",
    re.I,
)
# "Label: value" where the label is a known metadata key.
_META_INLINE = re.compile(
    r"^\s*(citation|cite\s+this\s+article|doi|received|revised|accepted|published|"
    r"funding|acknowledg(?:e?ments?)|author\s+contributions?|conflicts?\s+of\s+interest|"
    r"data\s+availability|abbreviations?|keywords?|academic\s+editor|correspondence|"
    r"supplementary\s+material|ethics?\s+statement|informed\s+consent|"
    r"institutional\s+review\s+board\s+statement|publisher'?s?\s+note)\s*:",
    re.I,
)
# A rail line is either a metadata label, a "label: value", or a bibliographic
# fragment — used as positive evidence that a page really has a metadata rail.
_RAIL_LINE = re.compile(
    r"(?:(?:citation|cite\s+this\s+article|doi|received|revised|accepted|published|"
    r"funding|acknowledg(?:e?ments?)|author\s+contributions?|conflicts?\s+of\s+interest|"
    r"data\s+availability|abbreviations?|keywords?|academic\s+editor|correspondence|"
    r"supplementary\s+material|ethics?\s+statement|informed\s+consent|"
    r"publisher'?s?\s+note)\s*:)"
    r"|(?:\b[A-Z][A-Za-z'’\-]{1,20},\s*(?:[A-Z]\.\s*){1,3}(?:;|$))",
    re.I,
)
# Bibliographic rail fragments: "Yang, W.; Zhai, R. 3DPhenoMVS: A" / "Wang, Y.; Hu, S.;"
_CITATION_FRAGMENT = re.compile(
    r"[A-Z][A-Za-z'’\-]{1,20},\s*(?:[A-Z]\.\s*){1,3}(?:;\s*[A-Z][A-Za-z'’\-]{1,20},\s*(?:[A-Z]\.\s*){1,3})+"
)
_MATH_CHARS = re.compile(r"[=+\-−×÷∑∫√±≤≥<>^_{}\[\]|∈∥·]")
# A right-aligned display-equation label such as "(12)".
_EQUATION_NUMBER = re.compile(r"\(\s*\d{1,3}\s*\)")


def _looks_like_meta_block(paragraph: RawParagraph, median_size: float) -> bool:
    """True only when a paragraph *is* front matter, not merely contains a word.

    Deliberately strict: the label must be at the start and the paragraph must be
    short. A looser test used to match ordinary prose ("Scientific articles are
    long…" matched the label "article"), which stripped real body text.
    """
    text = paragraph.text.strip()
    if not text or len(text) > 400 or not paragraph.lines:
        return False
    biggest = max((ln.size for ln in paragraph.lines), default=median_size)
    if biggest > median_size * 1.1:
        return False                       # titles are titles, not metadata
    first_line = paragraph.lines[0].text.strip()
    return bool(
        _META_LABEL.match(first_line)
        or _META_INLINE.match(first_line)
        or _RAIL_LINE.match(first_line)
    )


def _meta_line_index(paragraph: RawParagraph) -> Optional[int]:
    """Index of a metadata label line that sits *inside* a body paragraph.

    When a rail and the body are merged by the paragraph grouper, the rail line
    appears in the middle of body prose. Splitting there both frees the body from
    interleaved metadata and gives the metadata its own block.
    """
    if len(paragraph.lines) < 2:
        return None
    for index, line in enumerate(paragraph.lines):
        if index == 0:
            continue
        text = line.text.strip()
        if not text or len(text) > 120:
            continue
        if _META_LABEL.match(text) or _META_INLINE.match(text):
            return index
    return None


def _citation_leading(text: str) -> bool:
    """True for bibliographic fragments like "Yang, W.; Zhai, R. 3DPhenoMVS: A".

    These belong to the publisher's citation rail. When the rail and the body
    are horizontally interleaved, a rail line can be glued onto a body paragraph
    by the paragraph merger — this check catches that splinter afterwards.
    """
    probe = text.strip()[:90]
    return bool(_CITATION_FRAGMENT.match(probe))


def _split_at_citation(text: str) -> tuple[str, str]:
    """Split "body prose … Author, A.; Author, B. Title" into (body, rail)."""
    match = _CITATION_FRAGMENT.search(text)
    if not match:
        return text, ""
    return text[: match.start()].strip(), text[match.start() :].strip()


def _looks_like_formula_line(text: str) -> bool:
    """A line of a display equation rather than prose.

    PyMuPDF hands back equation spans in a scrambled order (subscripts and
    limits arrive as separate lines), so anything that reads like maths is better
    served by cropping the region as an image than by trusting the text order.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if len(stripped) <= 3 and _MATH_GLYPH.search(stripped):
        return True                        # lone brace / radical / limit glyph
    if len(stripped) > 110:
        return False
    if re.fullmatch(r"\(\s*\d{1,3}\s*\)", stripped):
        return True                        # equation number
    if not _MATH_CHARS.search(stripped) and not _MATH_GLYPH.search(stripped):
        return False
    letters = len(re.findall(r"[A-Za-z]", stripped))
    words = re.findall(r"[A-Za-z]{3,}", stripped)
    if len(words) >= 3 and letters >= 18:
        return False                       # reads like a sentence
    symbols = len(_MATH_CHARS.findall(stripped)) + len(_MATH_GLYPH.findall(stripped))
    return bool(symbols >= 2 and symbols / max(1, len(stripped)) >= 0.12)


# Private-use glyphs that equation fonts use for large braces and radicals: no
# text content, but unmistakably part of a display formula.
_MATH_GLYPH = re.compile(r"[\x00-\x1f\x7f\u2000-\u206f\ue000-\uf8ff]")
# Two or more measurements in a row: "0.42 cm, 0.98 cm, and 0.56 cm".
_MEASUREMENT_TAIL = re.compile(r"\d+(?:\.\d+)?\s*[a-zA-Z%]{0,4}\s*[,;].*\d", re.S)


def _reads_like_prose(text: str) -> bool:
    """True for a real sentence, even when it contains a formula fragment.

    "…an R2 of 0.72 and a MAPE of 17.23%…" carries maths characters but is prose:
    treating it as a display equation loses the text and changes its typeface.
    """
    stripped = text.strip()
    if not stripped or _looks_like_formula_line(stripped):
        return False
    return len(re.findall(r"[A-Za-z]{2,}", stripped)) >= 4 and len(stripped) >= 30
# Words that follow a bare number inside prose metadata ("29 June 2022) and …")
# and essentially never start a real section title.
_HEADING_STOPWORDS = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "and", "or", "of", "the",
    "in", "on", "at", "for", "with", "to", "by", "cm", "mm", "kg", "m", "s",
}


_FRONT_MATTER_HEADING = re.compile(
    r"^\s*(TYPE\b|ORIGINAL\s+RESEARCH|REVIEW\s+ARTICLE|RESEARCH\s+ARTICLE|"
    r"contents\s+lists\s+available|published\b|journal\s+homepage|"
    r"see\s+the\s+online\s+version|academic\s+editor|editorial\b|"
    r"research\s+article|short\s+communication|case\s+report)",
    re.I,
)
# Unnumbered headings that are genuinely part of a paper's structure. When a
# document uses numbered sections, only these plus the numbered ones stay in the
# outline — journal names, season rubrics and other furniture are dropped.
_STRUCTURAL_LABELS = {
    "abstract", "introduction", "background", "related work", "related works",
    "literature review", "methods", "method", "materials and methods",
    "methodology", "methods and materials", "experimental", "experiments",
    "results", "results and discussion", "discussion", "conclusions",
    "conclusion", "conclusions and outlook", "limitations", "future work",
    "outlook", "references", "bibliography", "acknowledgments",
    "acknowledgements", "funding", "appendix", "appendices", "supplementary",
    "supplementary material", "data availability", "author contributions",
    "conflicts of interest", "abbreviations", "keywords", "highlights",
    "摘要", "引言", "前言", "相关工作", "方法", "实验", "结果", "讨论",
    "结论", "参考文献", "致谢", "附录",
}


# A numbered heading that got glued to the sentence after it by the paragraph
# merger: "2.8. 3D Point Cloud from Active Sensors To evaluate the performance…"
_GLUED_HEADING = re.compile(
    r"(?P<heading>\d{1,2}(?:\.\d{1,2})*\.?\s+[A-Z][^.]{2,70}?)"
    r"(?=\s+[A-Z][a-z]+\s)"
)


def _looks_like_section_heading(text: str) -> bool:
    """True for headings we can recognise from text alone.

    Numbered headings are trusted only when the number is a plausible section
    index *and* the remainder actually starts with words. This is what keeps
    measurements, dates and list continuations out of the outline
    ("0.72 to 0.97.", "0.51 cm, 0.42 cm, …", "29 June 2022)", "100 images…").
    """
    stripped = text.strip()
    if not stripped or len(stripped) > 120:
        return False
    if _PAGE_NUMBER.match(stripped) or _FOLIO_ONLY.match(stripped):
        return False
    if re.match(r"^\s*(figure|table|fig\.|tab\.)\s*\d", stripped, re.I):
        return False
    # needs enough letters to be a real title, not a symbol or a bare number
    if len(re.findall(r"[A-Za-z\u4e00-\u9fff]", stripped)) < 4:
        return False
    if len(re.sub(r"[\W_]+", "", stripped)) < 6:
        return False                      # "∑" and similar fragments
    if _ROMAN_SECTION.match(stripped) and len(stripped) < 80:
        return True

    match = re.match(r"^\s*(\d{1,2}(?:\.\d{1,2})*)(\.?)(?=[\s.])\s*(.*)$", stripped)
    if not match:
        return False
    prefix, separator, rest = match.group(1), match.group(2), match.group(3).strip()
    if len(prefix.split(".")) > 3:
        return False                      # deep numbering is not our outline
    if prefix.startswith("0."):
        return False                      # "0.72 to 0.97" is a measurement, not a section
    # A title word may legitimately start with a digit ("2.8. 3D Point Cloud …"),
    # so accept letters and digits, but still reject units and dates by requiring
    # at least two letters inside the first word.
    if not rest or not rest[0].isalnum():
        return False
    first_word = rest.split()[0] if rest.split() else ""
    if len(first_word) < 2:
        return False                      # "2.8. 3" alone is a measurement tail
    if len(re.findall(r"[A-Za-z]", first_word)) < max(1, len(first_word) // 2):
        return False                      # "0.5 m" / "12 cm" style units
    if _MEASUREMENT_TAIL.search(rest):
        return False                      # "…cm, 0.42 cm, 0.98 cm, and 0.56 cm"
    if len(prefix.split(".")) == 1 and not separator:
        if not rest[0].isupper():
            return False                  # bare "8 positions where…"
        if not _HEADING_STOPWORDS.isdisjoint({rest.split()[0].lower()}):
            return False                  # bare "29 June 2022)…" is a date/metadata
    return len(rest) >= 2


def _span_text(span: dict) -> str:
    """Text of one span across PyMuPDF versions (rawdict vs dict output)."""
    text = span.get("text")
    if text:
        return text
    chars = span.get("chars")
    if chars:
        return "".join(str(ch.get("c", "")) for ch in chars)
    return ""


def _join_lines(lines: list[str]) -> str:
    """Join extracted lines into a paragraph, repairing hyphenated breaks."""
    out = ""
    for raw in lines:
        line = _MULTISPACE.sub(" ", raw.strip())
        if not line:
            continue
        if not out:
            out = line
            continue
        if _HYPHEN_END.search(out):
            out = _HYPHEN_END.sub(r"\1", out) + line
        else:
            out = out + " " + line
    return out.strip()


@dataclass
class RawLine:
    text: str
    bbox: tuple[float, float, float, float]
    size: float
    bold: bool
    page: int
    column: int = 0
    colour: Optional[tuple[float, float, float]] = None
    cells: Optional[list[tuple[float, float, str]]] = None   # geometric cell runs
    # (text, bold, italic) per span: keeps inline emphasis inside a paragraph
    runs: list[tuple[str, bool, bool]] = field(default_factory=list)


@dataclass
class RawParagraph:
    lines: list[RawLine] = field(default_factory=list)
    kind_hint: str = "text"
    image_path: Optional[str] = None
    table_html: Optional[str] = None
    table_rows: Optional[list[list[str]]] = None
    caption: Optional[str] = None
    latex: Optional[str] = None
    flags: list[str] = field(default_factory=list)
    explicit_bbox: Optional[tuple[float, float, float, float]] = None
    # True when the last line runs all the way to the column's right edge: the
    # paragraph was cut by the measure (or by a page break), not finished. Only
    # meaningful for justified text, where a final line stops short of the edge.
    tail_full: bool = False


    @property
    def bbox(self) -> tuple[float, float, float, float]:
        if not self.lines:
            return self.explicit_bbox or (0.0, 0.0, 0.0, 0.0)
        xs0 = [ln.bbox[0] for ln in self.lines]
        ys0 = [ln.bbox[1] for ln in self.lines]
        xs1 = [ln.bbox[2] for ln in self.lines]
        ys1 = [ln.bbox[3] for ln in self.lines]
        return (min(xs0), min(ys0), max(xs1), max(ys1))

    @property
    def text(self) -> str:
        return self._build()[0]

    @property
    def emphasis(self) -> list[tuple[int, int, str]]:
        """(start, end, style) runs over `text` where the text is bold/italic."""
        return self._build()[1]

    def _build(self) -> tuple[str, list[tuple[int, int, str]]]:
        """Join the lines exactly like the old text property, and record emphasis.

        Built in one pass so the emphasis offsets always match the returned text:
        the same hyphen repair and whitespace collapsing applies to both.
        """
        out = ""
        marks: list[tuple[int, int, str]] = []
        for line in self.lines:
            pieces = line.runs or [(line.text, line.bold, False)]
            parts = _trim_runs(pieces)
            if not parts:
                continue
            if out:
                if _HYPHEN_END.search(out):
                    out = _HYPHEN_END.sub(r"\1", out)
                    if marks and marks[-1][1] > len(out):
                        start, _end, style = marks[-1]
                        if start < len(out):
                            marks[-1] = (start, len(out), style)
                        else:
                            marks.pop()
                else:
                    out += " "
            for part, bold, italic in parts:
                part = _MULTISPACE.sub(" ", part)
                if not part:
                    continue
                style = (
                    "bold italic" if bold and italic else
                    "bold" if bold else
                    "italic" if italic else ""
                )
                start = len(out)
                out += part
                if style:
                    if marks and marks[-1][2] == style and marks[-1][1] == start:
                        marks[-1] = (marks[-1][0], len(out), style)
                    else:
                        marks.append((start, len(out), style))
        lead = len(out) - len(out.lstrip())
        if lead:
            marks = [(max(0, s - lead), e - lead, style) for s, e, style in marks if e > lead]
        out = out.strip()
        marks = [(s, min(e, len(out)), style) for s, e, style in marks if s < len(out)]
        return out, marks


def _trim_runs(pieces: list[tuple[str, bool, bool]]) -> list[tuple[str, bool, bool]]:
    """Drop the whitespace a PDF puts around a line, keeping run boundaries."""
    raw = "".join(piece[0] for piece in pieces)
    if not raw.strip():
        return []
    lead = len(raw) - len(raw.lstrip())
    end = len(raw.rstrip())
    out: list[tuple[str, bool, bool]] = []
    cursor = 0
    for text, bold, italic in pieces:
        start = cursor
        cursor += len(text)
        low, high = max(start, lead), min(cursor, end)
        if high > low:
            out.append((text[low - start : high - start], bold, italic))
    return out


# ------------------------------------------------------------------- layout

def _line_step_threshold(steps: list[float], line_height: float) -> float:
    """Vertical step (previous line top → next line top) that starts a paragraph.

    Working from line *tops* rather than gaps sidesteps line boxes that overlap
    or carry ascender/descender padding, which is what makes fixed ratio rules
    shatter paragraphs on some publishers' PDFs.

    Two safeguards matter more than elegance here:
      * the threshold can never fall below the document's own line pitch, or
        uniform body text gets split one line per block;
      * a 2-means split is trusted only when the two clusters are clearly
        distinct, otherwise we fall back to a multiple of the pitch.
    """
    pitch_values = [value for value in steps if 0.2 * line_height < value < 4.0 * line_height]
    if len(pitch_values) < 4:
        pitch_values = [value for value in steps if value > 0] or steps
    if not pitch_values:
        return max(2.0, line_height * 1.5)
    ordered = sorted(pitch_values)
    pitch = statistics.median(ordered)
    floor = max(2.0, pitch * 1.3, line_height * 1.25)

    low, high = ordered[0], ordered[-1]
    if high <= low * 1.3:
        return floor
    for _ in range(24):
        low_group = [v for v in pitch_values if abs(v - low) <= abs(v - high)]
        high_group = [v for v in pitch_values if abs(v - low) > abs(v - high)]
        if not low_group or not high_group:
            return floor
        new_low = sum(low_group) / len(low_group)
        new_high = sum(high_group) / len(high_group)
        if abs(new_low - low) < 0.01 and abs(new_high - high) < 0.01:
            low, high = new_low, new_high
            break
        low, high = new_low, new_high
    if high < low * 1.3:
        return floor
    return max(floor, (low + high) / 2.0)


def _y_overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def _inside_any(
    bbox: tuple[float, float, float, float],
    rects: list[tuple[float, float, float, float]],
    threshold: float = 0.55,
) -> bool:
    """True when most of `bbox` sits inside one of `rects`."""
    area = max(1e-6, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
    for rect in rects:
        overlap_w = _y_overlap((bbox[0], bbox[2]), (rect[0], rect[2]))
        overlap_h = _y_overlap((bbox[1], bbox[3]), (rect[1], rect[3]))
        if (overlap_w * overlap_h) / area >= threshold:
            return True
    return False


def _modal_start(values: list[float]) -> Optional[tuple[float, int]]:
    """The most frequent near-aligned value, as (value, count)."""
    if not values:
        return None
    best: Optional[tuple[float, int]] = None
    for candidate in sorted(values):
        count = sum(1 for other in values if abs(other - candidate) <= 3.0)
        if best is None or count > best[1]:
            best = (candidate, count)
    return best


RAIL_MIN_SPAN_RATIO = 0.35
RAIL_MIN_LABELS = 2


def _split_rail(lines: list[RawLine], boundary: float, page_width: float) -> bool:
    """Tag lines left/right of a rail boundary using line width.

    The boundary itself comes from `detect_gutter`; width decides which side each
    line belongs to, so a rail line that overhangs the boundary (a long DOI or
    author list) is not mistaken for body text.
    """
    width = max(1.0, page_width - boundary)
    for line in lines:
        narrow = (line.bbox[2] - line.bbox[0]) < width * 0.55
        line.column = -1 if narrow else 1
    return True


def _railed_page_columns(lines: list[RawLine], page_width: float) -> set[int]:
    """Column ids for a metadata rail, but only when there is positive evidence.

    Geometry alone cannot separate a rail from body text: on a single-column page
    the margin, page numbers and short lines all look "narrow", and a real
    two-column page has a wide left column. So the rail is accepted only when the
    left band actually contains publisher metadata labels ("Citation:",
    "Received:", "Keywords:" …). Without that evidence the page is left alone.
    """
    if len(lines) < 20:
        return set()
    tolerance = max(4.0, page_width * 0.01)
    starts = sorted(ln.bbox[0] for ln in lines)
    clusters: list[list[float]] = []
    for value in starts:
        if clusters and value - clusters[-1][-1] <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    required = max(6, len(lines) * 0.18)
    strong = [c for c in clusters if len(c) >= required]
    if len(strong) < 2:
        return set()
    strong.sort(key=lambda c: statistics.median(c))
    left_start = statistics.median(strong[0])
    if left_start > page_width * 0.08:
        return set()                                  # not hugging the margin
    left_lines = [ln for ln in lines if abs(ln.bbox[0] - left_start) <= tolerance]
    if len(left_lines) < required:
        return set()
    labels = sum(1 for line in left_lines if _RAIL_LINE.search(line.text.strip()))
    if labels < RAIL_MIN_LABELS:
        return set()                                  # no metadata evidence
    span = max(ln.bbox[3] for ln in left_lines) - min(ln.bbox[1] for ln in left_lines)
    page_height = max(ln.bbox[3] for ln in lines) - min(ln.bbox[1] for ln in lines)
    if page_height <= 0 or span / page_height < RAIL_MIN_SPAN_RATIO:
        return set()
    return {-1, -2}


def _body_start_for_rail(lines: list[RawLine], page_width: float) -> Optional[float]:
    """X of the body column when a single-column page carries a narrow rail.

    Only used when `detect_gutter` found no boundary, so classic two-column pages
    never reach here. The body start is the most common line start with a wide
    line *span*, which excludes page numbers and section rubrics.
    """
    wide = [
        line
        for line in lines
        if (line.bbox[2] - line.bbox[0]) >= page_width * 0.5
    ]
    if len(wide) < max(5, len(lines) * 0.15):
        return None
    modal = _modal_start([line.bbox[0] for line in wide])
    if modal is None:
        return None
    body_start, _count = modal
    if body_start <= page_width * 0.03:
        return None
    return float(body_start)


def _column_margin(lines: list[RawLine]) -> Optional[float]:
    """Left margin of the body text, derived from line width.

    The indent of a paragraph's first line is the clearest "a new paragraph starts
    here" signal that does not depend on the gap between lines, which matters for
    layouts that separate paragraphs purely by indentation. The margin is the most
    common left edge among body-width lines, so rail text, folios and centred
    captions do not skew it.
    """
    if not lines:
        return None
    widths = sorted(ln.bbox[2] - ln.bbox[0] for ln in lines)
    widest = widths[int(len(widths) * 0.75)] if widths else 0.0
    if widest < 120:
        return None
    margin = _modal_start(
        [ln.bbox[0] for ln in lines if (ln.bbox[2] - ln.bbox[0]) >= widest * 0.5]
    )
    return margin[0] if margin else None


def _is_rail_paragraph(
    para: RawParagraph, side_column: int, median_size: float = 0.0
) -> bool:
    """True when a paragraph really belongs to the metadata rail.

    Only the dedicated rail split (negative column ids) and a *narrow detected
    side column* qualify. Two guards matter:
      * "column == 0" must never mean rail — that happens when the detected side
        column is the left one, and it used to swallow whole body paragraphs;
      * a paragraph set larger than the body is a title/heading, not rail text,
        even though a wide title's first line may start left of the rail boundary.
    """
    if side_column <= 0 and not any(ln.column < 0 for ln in para.lines):
        return False
    lines = [ln for ln in para.lines if ln.text.strip()]
    if not lines:
        return False
    if median_size:
        biggest = max((ln.size for ln in lines), default=median_size)
        if biggest > median_size * 1.15:
            return False
    rail_lines = sum(
        1 for ln in lines if ln.column < 0 or (side_column > 0 and ln.column == side_column)
    )
    if rail_lines < len(lines) * 0.8:
        return False
    if sum(len(ln.text.strip()) for ln in lines) > 300:
        return False
    return max(len(ln.text.strip()) for ln in lines) <= 120


_SENTENCE_END = re.compile(r"""[.。!！?？:：;；]\s*[»"”'’)\]]*$""")
# A paragraph that continues onto the next page starts flush with the body margin
# and, in journals, carries the "(Continued)" marker.
_CONTINUED = re.compile(r"\(?\s*(continued|cont\.?)\s*\)?", re.I)


def _ends_mid_sentence(text: str) -> bool:
    """True when a block looks cut off rather than properly finished."""
    stripped = text.strip()
    if len(stripped) < 60:
        return False
    if not stripped:
        return False
    # lowercase or connective ending is the giveaway of a page-break split
    tail = stripped[-24:]
    if _SENTENCE_END.search(stripped):
        return False
    return bool(re.search(r"[a-z,;]$|\b(and|or|of|the|to|in|with|that|which|for|as)$", tail))


def _join_page_split_paragraphs(blocks: list[Block]) -> None:
    """Re-unite paragraphs that the layout split into two blocks.

    Two independent signals say "this text continues":

    * the block's last line reaches the column's right edge, so the measure cut
      it (this is the only signal that works in the block-style layouts MDPI,
      Frontiers and Elsevier use, where no paragraph is indented at all);
    * the text stops mid-sentence.

    A merge is vetoed when the following block opens a new structural unit — a
    section heading, a run-in label such as "Stem length:", a caption — or when a
    figure/table/equation block sits between the two.
    """
    ignorable = {"header", "footer", "meta", "caption"}
    # Identity, not equality: Block is a pydantic model, so `in` / `remove` would
    # compare field values and could drop a different block that happens to look
    # the same (two identical figure labels, for instance).
    texts = [b for b in sorted(blocks, key=lambda b: b.order) if b.type == "text"]
    merged = 0
    for index in range(len(texts) - 1):
        tail = texts[index]
        if not any(b is tail for b in blocks):
            continue
        if not tail.text.strip():
            continue
        tail_full = "tail-full" in tail.flags
        mid_sentence = _ends_mid_sentence(tail.text)
        if not tail_full and not mid_sentence:
            continue
        # Look a few blocks ahead: the next text block is often the running head
        # (still typed "text" at this point), a figure label or a caption between
        # the two halves of a paragraph.
        for head in texts[index + 1 : index + 5]:
            if not any(b is head for b in blocks) or not head.text.strip():
                continue
            if head.page > tail.page + 1:
                break
            low, high = sorted((tail.order, head.order))
            between = [b for b in blocks if low < b.order < high]
            blocking = [
                b
                for b in between
                if b.type not in ignorable
                and not _is_running_head_like(b)
                and not _is_figure_label(b)
            ]
            if blocking:
                # A float (figure, table, display equation) can be placed
                # between the two halves of a paragraph a page break cut
                # apart. When both signals are unmistakable — the line was cut
                # by the measure and the text resumes mid-sentence — the float
                # is not a boundary.
                strong = (
                    tail_full
                    and bool(re.match(r"^[a-z(\[]", head.text.lstrip()))
                    and all(
                        b.type in {"figure", "table", "formula", "footnote"}
                        for b in blocking
                    )
                )
                if not strong:
                    break
            if head.page == tail.page:
                if tail.column != head.column:
                    continue
                gap = head.bbox.y0 - tail.bbox.y1
                if gap < -3.0:
                    continue
                if gap > max(30.0, tail.size * 2.6):
                    break
            elif head.page == tail.page + 1:
                # A running head is short and pinned to the very top; body text
                # on the next page can legitimately start just as high, so
                # length and shape decide, not y alone.
                if _is_running_head_like(head):
                    continue
                if (head.bbox.x1 - head.bbox.x0) < 160:
                    continue
                # Column indices are per page: a single-column page and a page
                # with a metadata rail number the body column differently, so
                # the left edge of the text is the reliable comparison.
                if abs(head.bbox.x0 - tail.bbox.x0) > 14.0:
                    break
                margin = _column_margin_from_block(
                    [b for b in blocks if b.page == head.page]
                )
                if margin is not None and head.bbox.x0 - margin > 8:
                    break                 # indented → a genuinely new paragraph
            else:
                break

            if _opens_structural_unit(head.text):
                break

            if mid_sentence and not tail_full and not re.match(r"^[a-z(]", head.text.lstrip()):
                # an unfinished sentence followed by a capitalised sentence is
                # ambiguous; require the typographic cut signal for that case
                break

            tail.text = (tail.text.rstrip() + " " + head.text.lstrip()).strip()
            if head.caption:
                tail.caption = ((tail.caption or "") + " " + head.caption).strip()
            tail.flags = [f for f in tail.flags if f != "tail-full"]
            if "tail-full" in head.flags:
                tail.flags.append("tail-full")
            tail.bbox = BBox(
                x0=min(tail.bbox.x0, head.bbox.x0),
                # keep the tail's own vertical extent: the block still starts
                # on the tail's page, and mixing in the next page's y would
                # make the original-page highlight point at nothing
                y0=tail.bbox.y0,
                x1=max(tail.bbox.x1, head.bbox.x1),
                y1=tail.bbox.y1,
            )
            blocks.remove(head)
            merged += 1
            break
    for index, block in enumerate(sorted(blocks, key=lambda b: b.order)):
        block.order = index
    return merged


def _join_page_edges(blocks: list[Block]) -> int:
    """Last resort for page-break continuations that a float blocked.

    Only the very last body block of a page and the very first body block of the
    next page are considered, and the continuation must start lowercase (or open a
    bracket) — a fresh paragraph essentially never does. That narrowness is what
    makes it safe to ignore the figure, table or caption sitting between them.
    """
    joined = 0
    pages = sorted({b.page for b in blocks})
    for page in pages[:-1]:
        tail_candidates = sorted(
            (b for b in blocks if b.page == page and b.type == "text"), key=lambda b: b.order
        )
        head_candidates = sorted(
            (b for b in blocks if b.page == page + 1 and b.type == "text"),
            key=lambda b: b.order,
        )
        if not tail_candidates or not head_candidates:
            continue
        tail = tail_candidates[-1]
        if not ("tail-full" in tail.flags or _ends_mid_sentence(tail.text)):
            continue
        head = None
        for candidate in head_candidates[:3]:
            if _is_running_head_like(candidate) or _is_figure_label(candidate):
                continue
            if not re.match(r"^[a-z(\[]", candidate.text.lstrip()):
                break
            head = candidate
            break
        if head is None:
            continue
        if abs(head.bbox.x0 - tail.bbox.x0) > 14.0:
            continue
        if (head.bbox.x1 - head.bbox.x0) < 160:
            continue
        tail.text = (tail.text.rstrip() + " " + head.text.lstrip()).strip()
        if head.caption:
            tail.caption = ((tail.caption or "") + " " + head.caption).strip()
        tail.flags = [f for f in tail.flags if f != "tail-full"]
        if "tail-full" in head.flags:
            tail.flags.append("tail-full")
        blocks.remove(head)
        joined += 1
    for index, block in enumerate(sorted(blocks, key=lambda b: b.order)):
        block.order = index
    return joined


def _is_figure_label(block) -> bool:
    """A stray "(a)" / "A B" block: a figure panel label, not a paragraph."""
    text = block.text.strip()
    if not text or len(text) > 28:
        return False
    if re.fullmatch(r"[\(\[]?[A-Za-z0-9]{1,3}[\)\].]?", text):
        return True
    words = text.split()
    return len(words) <= 4 and not re.search(r"[.!?;:]", text) and len(text) <= 24


def _is_running_head_like(block) -> bool:
    """A short line pinned to the top of a page: journal name, folio, credit."""
    text = block.text.strip()
    if not text or len(text) > 90:
        return False
    if _PAGE_NUMBER.match(text) or _FOLIO_ONLY.match(text):
        return True
    # A continuation line starts lowercase (or opens a bracket); a running head
    # never does, so this keeps real body text at the top of a page.
    if re.match(r"^[a-z(\[]", text):
        return False
    return block.bbox.y1 <= 90.0


def _opens_structural_unit(text: str) -> bool:
    """True when a block starts something new rather than continuing prose."""
    stripped = text.lstrip()
    if not stripped:
        return True
    if _looks_like_section_heading(stripped):
        return True
    if _CAPTION_START.match(stripped):
        return True
    return bool(_RUN_IN_LABEL.match(stripped))


# "Stem length: Stem length is defined as …" — a labelled paragraph opener
_RUN_IN_LABEL = re.compile(r"^[A-Z][A-Za-z][A-Za-z0-9 \-/()]{0,30}:")


def _column_margin_from_block(blocks: list[Block]) -> Optional[float]:
    """Left margin of the body text on a page, from the blocks available there."""
    candidates = [
        b.bbox.x0
        for b in blocks
        if b.type in ("text", "heading") and (b.bbox.x1 - b.bbox.x0) >= 200
    ]
    if not candidates:
        return None
    modal = _modal_start(candidates)
    return modal[0] if modal else None


def _front_matter_first(blocks: list[Block]) -> None:
    """Move every non-body block ahead of the body, in reading order.

    Publishers scatter metadata (journal name, citation rail, received/accepted
    dates, licence note) through the first page, which is where the text flow
    interleaves with the abstract and the opening paragraphs. The reader wants the
    body unbroken, so front matter and running heads/formats are collected into a
    leading section instead of being interleaved.
    """
    front = [b for b in blocks if b.type in ("meta", "header", "footer")]
    body = [b for b in blocks if b.type not in ("meta", "header", "footer")]
    if not front:
        return
    front.sort(key=lambda b: (b.page, b.bbox.y0, b.bbox.x0))
    body.sort(key=lambda b: b.order)
    ordered = front + body
    for index, block in enumerate(ordered):
        block.order = index
    blocks[:] = ordered


def _interleaves_meta_with_body(blocks: list[Block]) -> bool:
    """True when non-body blocks are scattered between body blocks in reading order."""
    seen_body = False
    for block in sorted(blocks, key=lambda b: b.order):
        if block.type in ("header", "footer", "meta"):
            if seen_body:
                return True
        elif block.type not in ("", None):
            seen_body = True
    return False


def detect_gutter(
    boxes: list[tuple[float, float, float, float]],
    page_width: float,
    min_gap_ratio: float = 0.035,
) -> Optional[float]:
    """Return the x of a column boundary when the page has two text columns.

    Method: find the *line-start modes*. A two-column page (including the
    "narrow metadata rail + body" layout used by MDPI/Frontiers) shows two
    strongly repeated left edges; the left-most mode is the boundary, provided a
    real column of text starts to its right.

    An earlier version took the most frequent start as the body and then looked
    for the second column *to its right* — which silently failed whenever the
    rail was the left column and the body the right one, leaving the two streams
    interleaved by y and corrupting both reading order and segmentation.
    """
    if len(boxes) < 10:
        return None
    tolerance = max(4.0, page_width * 0.01)
    starts = sorted(b[0] for b in boxes)
    clusters: list[list[float]] = []
    for value in starts:
        if clusters and value - clusters[-1][-1] <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    strong = [c for c in clusters if len(c) >= max(5, len(boxes) * 0.15)]
    if len(strong) < 2:
        return None
    strong.sort(key=lambda c: statistics.median(c))
    # Try each strong start as the boundary between two columns and keep the
    # left-most one that actually has text on both sides. For a normal two-column
    # page the left column starts at the page margin, so its own start is rejected
    # (nothing lies to its left) and the second column's start wins instead.
    for cluster in strong:
        boundary = statistics.median(cluster)
        if boundary < page_width * 0.03 or boundary > page_width * 0.8:
            continue
        left = [b for b in boxes if b[2] <= boundary + 1]
        right = [b for b in boxes if b[0] >= boundary - 1]
        if len(left) < max(4, len(boxes) * 0.1):
            continue
        if len(right) < max(4, len(boxes) * 0.12):
            continue
        left_span = max(b[3] for b in left) - min(b[1] for b in left)
        right_span = max(b[3] for b in right) - min(b[1] for b in right)
        if min(left_span, right_span) < 60:
            continue
        return float(boundary)
    return None


def classify_columns(
    boxes: list[tuple[float, float, float, float]], page_width: float
) -> tuple[list[int], str]:
    """Assign a column index to each box; return (columns, alignment)."""
    gutter = detect_gutter(boxes, page_width, settings.column_min_gap_ratio)
    if gutter is None:
        return [0] * len(boxes), "single"
    cols: list[int] = []
    spanning = 0
    for x0, _y0, x1, _y1 in boxes:
        if x0 < gutter - 1 and x1 > gutter + 1:
            cols.append(-1)  # full-width block (title, wide figure, table)
            spanning += 1
        elif x1 <= gutter + 1:
            cols.append(0)
        else:
            cols.append(1)
    alignment = "double" if spanning <= max(2, 0.15 * len(boxes)) else "mixed"
    return cols, alignment


# ------------------------------------------------------------------- figures

def _crop_region(
    page: pymupdf.Page,
    bbox: tuple[float, float, float, float],
    doc_key: str,
    name: str,
) -> Optional[str]:
    """Crop a page region at high DPI (shared by figures and equations)."""
    try:
        clip = pymupdf.Rect(*bbox)
        if clip.is_empty or clip.width < 8 or clip.height < 8:
            return None
        matrix = pymupdf.Matrix(settings.render_dpi / 72.0, settings.render_dpi / 72.0)
        pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
        out_dir = ASSET_DIR / doc_key
        out_dir.mkdir(parents=True, exist_ok=True)
        pix.save(out_dir / name)
        return f"{doc_key}/{name}"
    except Exception:
        return None


def _save_figure(
    page: pymupdf.Page,
    bbox: tuple[float, float, float, float],
    doc_key: str,
    index: int,
) -> Optional[str]:
    """Crop the region at high DPI so the figure stays readable in the UI."""
    return _crop_region(page, bbox, doc_key, f"p{page.number + 1:04d}_fig{index:03d}.png")


def _table_to_html(rows: list[list[str]]) -> str:
    parts = ['<table class="doc-table">']
    for r_i, row in enumerate(rows):
        parts.append("<tr>")
        for cell in row:
            tag = "th" if r_i == 0 else "td"
            parts.append(f"<{tag}>{html.escape(cell or '')}</{tag}>")
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)


# ------------------------------------------------------------------- parser

def _region_without_prose(
    region: tuple[float, float, float, float],
    fragments: list[tuple[float, float, float, float, str]],
) -> Optional[tuple[float, float, float, float]]:
    """Trim a candidate equation region down to its formula lines.

    Cropping must never cost body text, but a sentence that merely sits inside a
    dense maths band must not cancel the crop either: the equation is kept and
    the prose line is dropped from the region. Returns None when no formula
    fragment remains, or when a sentence would still be inside the trimmed band.
    """
    left, top, right, bottom = region
    inside = [
        f for f in fragments
        if f[1] >= top - 3 and f[3] <= bottom + 3 and f[0] >= left - 3 and f[2] <= right + 3
    ]
    prose = [f for f in inside if _reads_like_prose(f[4])]
    if not prose:
        return region
    maths = sorted(
        (f for f in inside if not _reads_like_prose(f[4])), key=lambda f: (f[1], f[0])
    )
    runs: list[list[tuple[float, float, float, float, str]]] = []
    for fragment in maths:
        if runs and fragment[1] - runs[-1][-1][3] <= 6.0:
            runs[-1].append(fragment)
        else:
            runs.append([fragment])
    if not runs:
        return None
    run = max(runs, key=len)
    new_top = min(f[1] for f in run)
    new_bottom = max(f[3] for f in run)
    if new_bottom - new_top < 4.0 or (right - left) < 30.0:
        return None
    if any(new_top - 3 <= p[1] and p[3] <= new_bottom + 3 for p in prose):
        return None
    return (left, new_top, right, new_bottom)


class PDFParser:
    def __init__(self, path: Path, doc_id: str, ocr: bool = False, force_ocr: bool = False) -> None:
        self.path = path
        self.doc_id = doc_id
        self.warnings: list[str] = []
        self.asset_key = doc_id
        self.ocr = ocr
        self.force_ocr = force_ocr
        self.ocr_pages = 0
        self.ocr_confidences: list[float] = []
        self._ocr_page_indexes: set[int] = set()
        self.front_matter_hoisted = False

    def parse(self) -> tuple[list[Block], list[PageInfo], ParseReport, dict]:
        started = time.perf_counter()
        ocr_ready = False
        if self.ocr:
            ocr_ready, detail = ocr_status()
            if not ocr_ready:
                self.warnings.append(f"OCR 不可用，已回退到文本层解析：{detail}")
        pdf = pymupdf.open(self.path)
        try:
            blocks: list[Block] = []
            pages: list[PageInfo] = []
            stats: dict = {
                "chars": 0, "garbage": 0, "figures": 0, "tables": 0,
                "formulas": 0, "paragraphs": 0, "ocr": 0,
                "sizes": [], "alignments": [],
            }
            metadata = self._metadata(pdf)

            for page_index in range(pdf.page_count):
                page = pdf[page_index]
                page_blocks, page_stats = self._parse_page(
                    page, page_index, len(blocks), ocr_ready
                )
                blocks.extend(page_blocks)
                for key, value in page_stats.items():
                    if key in ("sizes", "alignments"):
                        stats[key].extend(value)
                    else:
                        stats[key] = stats.get(key, 0) + value
                pages.append(
                    PageInfo(
                        index=page_index,
                        width=float(page.rect.width),
                        height=float(page.rect.height),
                        rotation=int(page.rotation or 0),
                        block_count=len(page_blocks),
                    )
                )

            self._refine(blocks)

            channel = "text-layer"
            if self.ocr_pages:
                channel = "ocr" if self.ocr_pages >= max(1, int(pdf.page_count * 0.5)) else "text-layer+ocr"
                mean_conf = (
                    sum(self.ocr_confidences) / len(self.ocr_confidences)
                    if self.ocr_confidences
                    else 0.0
                )
                self.warnings.append(
                    f"OCR 处理了 {self.ocr_pages}/{pdf.page_count} 页，平均置信度 {mean_conf:.2f}；"
                    "识别结果可能与原页面有差异，建议对照「原版页」"
                )

            report = ParseReport(
                text_coverage=stats["chars"] / max(1, pdf.page_count) / 2000.0,
                garbage_ratio=min(1.0, stats["garbage"] / max(1, stats["chars"])),
                table_count=stats["tables"],
                figure_count=stats["figures"],
                formula_count=stats["formulas"],
                paragraph_count=stats["paragraphs"],
                alignment=self._dominant_alignment(stats["alignments"]),
                channel=channel,
                ocr_pages=self.ocr_pages,
                ocr_confidence=(
                    round(sum(self.ocr_confidences) / len(self.ocr_confidences), 3)
                    if self.ocr_confidences
                    else 0.0
                ),
                warnings=list(self.warnings),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return blocks, pages, report, metadata
        finally:
            pdf.close()

    # -- internals ----------------------------------------------------------
    def _metadata(self, pdf: pymupdf.Document) -> dict:
        meta = pdf.metadata or {}
        title = (meta.get("title") or "").strip()
        authors = [
            a.strip() for a in re.split(r"[;,]| and ", meta.get("author") or "") if a.strip()
        ]
        if not title:
            title = self._form_title()
        return {"title": title, "authors": authors[:12]}

    def _form_title(self) -> str:
        """Read the document title from local form metadata (offline, no network)."""
        try:
            from pypdf import PdfReader

            fields = PdfReader(str(self.path)).get_fields() or {}
        except Exception:
            return ""
        for name in ("Title", "/Title", "title"):
            entry = fields.get(name)
            if isinstance(entry, dict):
                value = entry.get("/V") or entry.get("V")
                if value:
                    return str(value).strip()
            elif isinstance(entry, str):
                return entry.strip()
        return ""

    def _parse_page(
        self,
        page: pymupdf.Page,
        page_index: int,
        order_base: int,
        ocr_ready: bool = False,
    ) -> tuple[list[Block], dict]:
        stats: dict = {
            "chars": 0, "garbage": 0, "figures": 0, "tables": 0,
            "formulas": 0, "paragraphs": 0, "sizes": [], "alignments": [], "ocr": 0,
        }
        raw = page.get_text("rawdict")
        lines = self._lines_from_raw(raw, page_index)
        char_count = sum(len(line.text) for line in lines)

        if ocr_ready and settings.ocr_mode != "off" and self._should_ocr(page, lines, char_count):
            ocr_lines = self._ocr_lines(page, page_index)
            if ocr_lines:
                self.ocr_pages += 1
                lines = ocr_lines
                stats["ocr"] = 1
                self._ocr_page_indexes.add(page_index)
            elif not lines:
                self.warnings.append(f"page {page_index + 1}: OCR 未识别出任何文本")

        if not lines:
            self.warnings.append(f"page {page_index + 1}: no text layer")
            stats["alignments"].append("unknown")
            return [], stats

        stats["sizes"].extend(ln.size for ln in lines)

        # Tables first: cells would otherwise be treated as body text and even
        # invent a fake second column on single-column pages.
        table_paragraphs: list[RawParagraph] = []
        table_rects: list[tuple[float, float, float, float]] = []
        for table in self._find_tables(page):
            rows = self._table_rows(table)
            if not rows or not any(any(c.strip() for c in r) for r in rows):
                continue
            rect = tuple(float(v) for v in table.bbox)
            if not self._looks_like_table(rect, rows, lines):
                continue
            table_rects.append(rect)
            table_paragraphs.append(
                RawParagraph(
                    kind_hint="table",
                    table_html=_table_to_html(rows),
                    table_rows=rows,
                    explicit_bbox=rect,
                )
            )

        # Rule-only tables (horizontal rules but no vertical grid) are invisible
        # to the table finder, so rebuild those from their cell alignment.
        rule_tables, rule_regions = self._rule_based_tables(page, lines)
        if rule_tables:
            table_paragraphs.extend(rule_tables)
            table_rects.extend(rule_regions)

        if table_rects:
            # A table may only swallow text it actually reproduces. Rebuilding a
            # grid is lossy for merged cells, wrapped rows and footnotes, and the
            # lost lines are invisible once the region is cut out of the body.
            kept_lines: list[RawLine] = []
            dropped: dict[int, list[RawLine]] = {}
            for line in lines:
                owner = next(
                    (
                        i
                        for i, rect in enumerate(table_rects)
                        if _inside_any(line.bbox, [rect])
                    ),
                    None,
                )
                if owner is None:
                    kept_lines.append(line)
                else:
                    dropped.setdefault(owner, []).append(line)
            survivors: list[RawParagraph] = []
            for index, para in enumerate(table_paragraphs):
                inside = dropped.get(index, [])
                if inside:
                    cells = re.sub(r"\s+", "", "".join("".join(r) for r in (para.table_rows or [])))
                    raw = re.sub(r"\s+", "", "".join(line.text for line in inside))
                    if len(cells) < len(raw) * 0.8:
                        self.warnings.append(
                            f"page {page_index + 1}: 表格还原不完整，已保留原始文本以免丢失内容"
                        )
                        kept_lines.extend(inside)
                        continue
                survivors.append(para)
            table_paragraphs = survivors
            lines = kept_lines

        boxes = [ln.bbox for ln in lines]
        if boxes:
            cols, alignment = classify_columns(boxes, float(page.rect.width))
        else:
            cols, alignment = [], "unknown"
        for line, col in zip(lines, cols):
            line.column = col
        # A single-column page can still carry a narrow metadata rail beside the
        # abstract (MDPI/Frontiers). Only when no vertical boundary was found — so
        # real two-column pages keep the standard treatment — and only with actual
        # metadata labels as evidence.
        if alignment == "single":
            body_start = _body_start_for_rail(lines, float(page.rect.width))
            if body_start is not None and _railed_page_columns(lines, float(page.rect.width)):
                self.front_matter_hoisted = True
                _split_rail(lines, body_start, float(page.rect.width))
                alignment = "mixed"
        stats["alignments"].append(alignment)
        # A narrow side column is the publisher's metadata rail (article info,
        # citation, dates) or a reference line-number column — never body prose.
        side_column = 0
        if alignment == "double":
            column_widths: dict[int, list[float]] = {}
            for line in lines:
                column_widths.setdefault(line.column, []).append(line.bbox[2] - line.bbox[0])
            medians = {c: statistics.median(v) for c, v in column_widths.items() if c >= 0 and v}
            body_width = max(medians.values()) if medians else 0.0
            for col, width in medians.items():
                if width < body_width * 0.62:
                    side_column = col
                    break

        margin_x = _column_margin(lines) if lines else None
        paragraphs = (
            self._group_paragraphs(lines, side_column, margin_x) + table_paragraphs
        )

        paragraphs = self._insert_figures(
            page,
            page_index,
            paragraphs,
            table_rects,
            skip=self.ocr_pages > 0 and page_index in self._ocr_page_indexes,
        )
        paragraphs = self._insert_equations(page, page_index, paragraphs)
        paragraphs.sort(key=self._reading_order_key)

        out: list[Block] = []
        median_size = statistics.median(stats["sizes"]) if stats["sizes"] else 10.0
        for para in paragraphs:
            if not para.lines and not para.image_path and not para.table_html:
                continue
            text = para.text
            stats["chars"] += len(text) + len(para.caption or "")
            stats["garbage"] += len(_GARBAGE_CHARS.findall(text)) + len(_CID_GARBAGE.findall(text))
            if para.table_html:
                stats["tables"] += 1
            if para.image_path:
                stats["figures"] += 1
            if para.kind_hint == "text" and text:
                stats["paragraphs"] += 1
                # A paragraph that merely mentions an equation ("…with R2 = 0.72…")
                # is prose: retyping it as a formula changes its typeface and drops
                # it from translation. Only short, maths-dominated blocks qualify.
                if (
                    _FORMULA_HINT.search(text)
                    and len(text) < 220
                    and not _reads_like_prose(text)
                ):
                    para.kind_hint = "formula"
                    stats["formulas"] += 1
            bbox = para.bbox if para.lines else (0.0, 0.0, 0.0, 0.0)
            global_order = order_base + len(out)
            faint = bool(
                para.lines
                and para.lines[0].colour is not None
                and min(para.lines[0].colour) > 0.7      # light text on a band
            )
            out.append(
                Block(
                    # IDs must be unique across the whole document: numbering per
                    # page would collide and silently overwrite earlier pages in
                    # the database's primary key.
                    id=f"{self.doc_id}-b{global_order:05d}",
                    doc_id=self.doc_id,
                    order=global_order,
                    page=page_index,
                    type="header" if faint else para.kind_hint,  # type: ignore[arg-type]
                    text=text,
                    bbox=BBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3]),
                    column=max(0, para.lines[0].column) if para.lines else 0,
                    level=None if faint else self._heading_level(para, median_size),
                    size=max((ln.size for ln in para.lines), default=0.0),
                    image_path=para.image_path,
                    latex=para.latex,
                    caption=para.caption,
                    table_html=para.table_html,
                    table_rows=para.table_rows,
                    emphasis=[
                        {"start": start, "end": end, "style": style}
                        for start, end, style in para.emphasis
                        if style
                    ],
                    flags=list(para.flags)
                    + (["faint-text"] if faint else [])
                    + (["tail-full"] if para.tail_full else []),
                )
            )

        self._mark_headers_footers(out, float(page.rect.height))
        return out, stats

    @staticmethod
    def _reading_order_key(para: RawParagraph):
        """Full-width blocks (column -1) open a band, then left column, then right."""
        if para.lines:
            column = para.lines[0].column
        elif para.explicit_bbox is not None:
            column = 0  # tables/figure crops are treated as in-flow blocks
        else:
            return (0, 0.0)
        if column < 0:
            return (0, para.bbox[1])
        return (1, column * 1_000_000.0 + para.bbox[1])

    # -- OCR fallback -------------------------------------------------------
    def _should_ocr(self, page: pymupdf.Page, lines: list[RawLine], char_count: int) -> bool:
        """True when this page looks scanned, or when the user forced OCR."""
        if self.force_ocr or settings.ocr_mode == "force":
            return True
        if settings.ocr_mode == "off":
            return False
        if lines and char_count >= settings.ocr_min_text_chars:
            return False
        return image_coverage(page) >= 0.35

    def _ocr_lines(self, page: pymupdf.Page, page_index: int) -> list[RawLine]:
        result = ocr_page(page)
        if not result.lines:
            return []
        self.ocr_confidences.append(result.mean_confidence)
        heights = [ln.bbox[3] - ln.bbox[1] for ln in result.lines if ln.bbox[3] > ln.bbox[1]]
        median_height = statistics.median(heights) if heights else 11.0
        # OCR gives no font size; approximate one from the line box height so
        # heading detection and paragraph grouping keep working unchanged.
        synthetic_size = max(7.0, min(20.0, median_height * 0.78))
        return [
            RawLine(ln.text, ln.bbox, synthetic_size, False, page_index, 0)
            for ln in result.lines
        ]

    # -- text layer ---------------------------------------------------------
    def _lines_from_raw(self, raw: dict, page_index: int) -> list[RawLine]:
        lines: list[RawLine] = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                # PyMuPDF ≥1.26 exposes per-character data in `chars` and no
                # longer fills `text` for rawdict output; support both.
                text = "".join(_span_text(span) for span in spans)
                if not text.strip():
                    continue
                bbox = tuple(float(v) for v in line.get("bbox", (0, 0, 0, 0)))
                size = max((float(s.get("size", 10.0)) for s in spans), default=10.0)
                font = " ".join(str(s.get("font", "")) for s in spans).lower()
                bold = "bold" in font or "black" in font
                colour = self._span_colour(spans)
                cells = self._span_cells(spans)
                runs = self._span_runs(spans)
                lines.append(
                    RawLine(text, bbox, size, bold, page_index, 0, colour, cells, runs)  # type: ignore[arg-type]
                )
        lines.sort(key=lambda ln: (round(ln.bbox[1], 1), ln.bbox[0]))
        return lines

    @staticmethod
    def _span_runs(spans: list[dict]) -> list[tuple[str, bool, bool]]:
        """Per-span (text, bold, italic) runs, merged when the style repeats.

        PDFs mark emphasis per span, so this is where "some words in this
        paragraph are bold" survives; the line-level `bold` flag only says
        whether a whole line was bold.
        """
        runs: list[tuple[str, bool, bool]] = []
        for span in spans:
            text = _span_text(span)
            if not text:
                continue
            font = str(span.get("font", "")).lower()
            flags = int(span.get("flags", 0) or 0)
            bold = bool(flags & 2 ** 4) or any(
                token in font for token in ("bold", "black", "semibold", "demi")
            )
            italic = bool(flags & 2 ** 1) or any(
                token in font for token in ("italic", "oblique")
            )
            if runs and runs[-1][1] == bold and runs[-1][2] == italic:
                runs[-1] = (runs[-1][0] + text, bold, italic)
            else:
                runs.append((text, bold, italic))
        return runs

    @staticmethod
    def _span_cells(spans: list[dict]) -> list[tuple[float, float, str]]:
        """Merge spans into cell runs, splitting where the x-gap is large.

        Text-based column splitting is unreliable because PyMuPDF only inserts a
        space for gaps wider than a threshold and drops the rest, so a table row
        can read as one long string. Span geometry keeps the real column layout.
        """
        runs: list[tuple[float, float, str]] = []
        for span in spans:
            bbox = span.get("bbox")
            text = _span_text(span)
            if not bbox or not text.strip():
                continue
            x0, _y0, x1, _y1 = (float(v) for v in bbox)
            if runs and x0 - runs[-1][1] < 6.0:
                prev_x0, _prev_x1, prev_text = runs[-1]
                runs[-1] = (prev_x0, x1, prev_text + text)
            else:
                runs.append((x0, x1, text))
        return [(x0, x1, text.strip()) for x0, x1, text in runs if text.strip()]

    @staticmethod
    def _span_colour(spans: list[dict]) -> tuple[float, float, float] | None:
        """Average span colour, used to recognise journal branding (white text)."""
        values: list[tuple[float, float, float]] = []
        for span in spans:
            colour = span.get("color")
            if not isinstance(colour, int):
                continue
            values.append(
                (
                    ((colour >> 16) & 0xFF) / 255.0,
                    ((colour >> 8) & 0xFF) / 255.0,
                    (colour & 0xFF) / 255.0,
                )
            )
        if not values:
            return None
        count = len(values)
        return (
            sum(v[0] for v in values) / count,
            sum(v[1] for v in values) / count,
            sum(v[2] for v in values) / count,
        )

    def _group_paragraphs(
        self,
        lines: list[RawLine],
        side_column: int = 0,
        margin_x: Optional[float] = None,
    ) -> list[RawParagraph]:
        """Merge lines into paragraphs.

        Lines are grouped strictly inside their own column, so a two-column page
        never interleaves the two text streams; full-width lines (title, wide
        table) form their own paragraphs and open a band ahead of both columns.
        """
        if not lines:
            return []
        sizes = [ln.size for ln in lines if ln.size > 0]
        median_size = statistics.median(sizes) if sizes else 10.0
        paragraphs: list[RawParagraph] = []

        for column in sorted({ln.column for ln in lines}):
            group = sorted(
                (ln for ln in lines if ln.column == column),
                key=lambda ln: (round(ln.bbox[1], 1), ln.bbox[0]),
            )
            # learn this column's leading before merging anything
            steps = [
                group[i + 1].bbox[1] - group[i].bbox[1] for i in range(len(group) - 1)
            ]
            heights = [ln.bbox[3] - ln.bbox[1] for ln in group if ln.bbox[3] > ln.bbox[1]]
            typical_height = statistics.median(heights) if heights else 11.0
            step_limit = _line_step_threshold(steps, typical_height)
            # Right edge of the column: a line that reaches it was broken by the
            # measure, so its paragraph continues (page break or measure break).
            column_right = max((ln.bbox[2] for ln in group), default=0.0)

            current: list[RawLine] = []
            prev: Optional[RawLine] = None

            def flush() -> None:
                nonlocal current
                if current:
                    paragraph = RawParagraph(lines=list(current))
                    last = current[-1]
                    span = max(
                        [last.bbox[2] - ln.bbox[0] for ln in current] + [1.0]
                    )
                    paragraph.tail_full = last.bbox[2] >= column_right - max(3.0, 0.015 * span)
                    paragraphs.append(paragraph)
                    current = []

            for line in group:
                if prev is not None:
                    step = line.bbox[1] - prev.bbox[1]
                    size_delta = abs(line.size - prev.size)
                    is_heading_line = self._line_is_standalone(line)
                    # A first-line indent marks a new paragraph even when the line
                    # spacing is uniform — the usual layout for indented styles.
                    # Only treat it as a break when the previous line ran full
                    # width, so a wrapped short line is not mistaken for one.
                    indented = bool(
                        margin_x is not None
                        and line.bbox[0] > margin_x + 8
                        and line.bbox[0] < margin_x + 30
                        and (line.bbox[2] - line.bbox[0]) >= (prev.bbox[2] - prev.bbox[0]) * 0.8
                    )
                    prev_indented = bool(
                        margin_x is not None
                        and prev.bbox[0] > margin_x + 8
                        and prev.bbox[0] < margin_x + 30
                    )
                    starts_new = (
                        step > step_limit
                        or step < 0
                        or size_delta > max(1.6, prev.size * 0.2)
                        or (indented and not prev_indented)
                    )
                    if starts_new or is_heading_line or self._line_is_standalone(prev):
                        flush()
                current.append(line)
                prev = line
            flush()

        for para in paragraphs:
            text = para.text
            if not text:
                continue
            biggest = max((ln.size for ln in para.lines), default=median_size)
            sentences = len(re.findall(r"[.!?]\s|[.!?]$", text))
            # A heading line that ended up inside a paragraph must be split out.
            # We know exactly where it ends because we still have the line boxes,
            # so this needs no guessing about "where the title stops".
            if len(para.lines) > 1:
                head_lines = []
                rest_lines = list(para.lines)
                while rest_lines and _looks_like_section_heading(rest_lines[0].text.strip()):
                    head_lines.append(rest_lines.pop(0))
                if head_lines and len(rest_lines) >= 1:
                    paragraphs.append(RawParagraph(lines=head_lines, kind_hint="heading"))
                    if not rest_lines:
                        continue
                    para.lines = rest_lines
                    text = para.text
                    if not text:
                        continue
                # a metadata label buried mid-paragraph marks where a rail line was
                # glued into body prose: split it out instead of hiding the whole
                # paragraph as metadata
                meta_at = _meta_line_index(para)
                if meta_at is not None and meta_at >= 1:
                    before = para.lines[:meta_at]
                    after = para.lines[meta_at:]
                    paragraphs.append(RawParagraph(lines=after, kind_hint="meta"))
                    para.lines = before
                    text = para.text
                    if not text:
                        continue
            if _CAPTION_START.match(text):
                para.kind_hint = "caption"
            elif _looks_like_section_heading(text):
                para.kind_hint = "heading"
            elif _looks_like_meta_block(para, median_size):
                # front matter / sidebar rail: kept as its own type so the reader
                # can show it outside the body flow instead of interleaved
                para.kind_hint = "meta"
            elif (
                _is_rail_paragraph(para, side_column, median_size)
                and len(text) < 400
                and not _looks_like_section_heading(text)
            ):
                # anything else living in the narrow rail is front matter too
                para.kind_hint = "meta"
            elif (
                len(text) < 120
                and sentences == 0
                and not text.endswith((".", "。", ",", ";", ":"))
                and biggest >= median_size * 1.18
            ):
                # short, unpunctuated and visually larger than body text
                para.kind_hint = "heading"
            elif (
                _REF_START.match(text)
                and len(text) < 400
                and re.search(r"\b(19|20)\d{2}\b", text)
            ):
                para.kind_hint = "reference"
            elif len(text) < 90 and re.match(r"^\s*\d{1,2}\s", text):
                para.kind_hint = "footnote"
        return paragraphs

    @staticmethod
    def _line_is_standalone(line: RawLine) -> bool:
        """A line that must never be glued to its neighbours.

        This must stay conservative: treating body prose as standalone shatters
        paragraphs into one block per line, which is exactly the failure mode we
        hit on real MDPI layouts ("100 images were taken…" was read as a
        heading because it starts with a number).
        """
        text = line.text.strip()
        if not text:
            return True
        if _PAGE_NUMBER.match(text) or _FOLIO_ONLY.match(text):
            return True
        if _CAPTION_START.match(text) and len(text) < 200:
            return True
        if _looks_like_section_heading(text):
            return True
        return text.endswith(":") and len(text) < 60

    # -- rule-based tables --------------------------------------------------
    @staticmethod
    def _split_row(text: str, gutter: float = 3.0) -> list[str]:
        """Split a table row into cells at runs of 3+ spaces (pdfplumber style)."""
        return [cell.strip() for cell in re.split(r"\s{%d,}" % int(gutter), text) if cell.strip()]

    @staticmethod
    def _row_cells(line: RawLine) -> list[tuple[float, float, str]]:
        """Cells of a row, preferring geometric gaps over text spacing."""
        if line.cells and len(line.cells) >= 2:
            return line.cells
        # fall back to whitespace runs, deriving rough x positions from the glyph
        # pitch so alignment checks still have something to compare
        parts = [part for part in re.split(r"\s{3,}", line.text.strip()) if part]
        if len(parts) >= 2:
            width = max(1.0, line.bbox[2] - line.bbox[0])
            step = width / max(1, len(line.text))
            cells: list[tuple[float, float, str]] = []
            offset = 0
            for part in parts:
                start = line.text.find(part, offset)
                cells.append((line.bbox[0] + start * step, line.bbox[0] + (start + len(part)) * step, part))
                offset = start + len(part)
            return cells
        return []

    @staticmethod
    def _reject_pseudo_table(table_rows: list[list[str]]) -> bool:
        """Reject look-alikes that the row rhythm test happily groups.

        Two recurring false positives: display equations (left cell is maths,
        right cell is the equation number) and the reference list (left cell is
        the entry number, right cell is a full citation).
        """
        left = [row[0] for row in table_rows if row]
        right = [row[1] for row in table_rows if len(row) > 1]
        if not left or not right:
            return True
        # equations
        math_left = sum(1 for cell in left if _MATH_CHARS.search(cell))
        if math_left >= max(2, len(left) * 0.5):
            return True
        # reference lists: numbered left column + long right column
        numbered = sum(1 for cell in left if re.fullmatch(r"\[?\d{1,3}\]?\.?", cell.strip()))
        long_right = sum(1 for cell in right if len(cell) > 60)
        if numbered >= len(left) * 0.6 and long_right >= len(right) * 0.6:
            return True
        # generic prose table: either column reads like sentences rather than cells
        if sum(1 for cell in right if len(cell) > 90) >= len(right) * 0.6:
            return True
        if sum(1 for cell in left if len(cell) > 60 and len(cell.split()) >= 8) >= len(left) * 0.6:
            return True
        return False

    def _rule_based_tables(
        self, page: pymupdf.Page, lines: list[RawLine]
    ) -> tuple[list[RawParagraph], list[tuple[float, float, float, float]]]:
        """Rebuild tables that have horizontal rules but no vertical ones.

        PyMuPDF's table finder needs a full grid; many journal tables are
        rule-only (a line above the header, one below the last row), so they come
        through as ordinary paragraphs. Their rows are still recognisable: two
        cell runs separated by a wide gap, repeated down the page with a steady
        rhythm and aligned columns.
        """
        tables: list[RawParagraph] = []
        regions: list[tuple[float, float, float, float]] = []
        # A table row often arrives as several lines that share a baseline (one
        # per cell, because the cells are far apart in x). Group them first.
        groups: list[list[RawLine]] = []
        for line in sorted(lines, key=lambda ln: (round(ln.bbox[1], 1), ln.bbox[0])):
            if groups and abs(groups[-1][0].bbox[1] - line.bbox[1]) <= 2.5:
                groups[-1].append(line)
            else:
                groups.append([line])

        rows: list[tuple[RawLine, list[tuple[float, float, str]]]] = []
        for group in groups:
            if len(group) < 2:
                continue
            merged = sorted(group, key=lambda ln: ln.bbox[0])
            row_line = RawLine(
                text=" ".join(ln.text.strip() for ln in merged),
                bbox=(
                    merged[0].bbox[0],
                    min(ln.bbox[1] for ln in merged),
                    merged[-1].bbox[2],
                    max(ln.bbox[3] for ln in merged),
                ),
                size=merged[0].size,
                bold=any(ln.bold for ln in merged),
                page=merged[0].page,
                column=merged[0].column,
            )
            cells = [(ln.bbox[0], ln.bbox[2], ln.text.strip()) for ln in merged]
            if len(row_line.text) > 140:
                continue
            # table cells are short labels/values; two prose fragments sharing a
            # baseline (e.g. two column headings) must not be read as one row
            if any(len(text) > 70 and len(text.split()) >= 8 for _x0, _x1, text in cells):
                continue
            if len(cells) == 2 and min(len(cells[0][2]), len(cells[1][2])) > 26:
                continue
            widest = max(
                (cells[i + 1][0] - cells[i][1], i) for i in range(len(cells) - 1)
            )
            if widest[0] < 12.0:
                continue                      # just a wide word space
            split_at = widest[1]
            rows.append(
                (
                    row_line,
                    [
                        (cells[0][0], cells[split_at][1], " ".join(c[2] for c in cells[: split_at + 1])),
                        (cells[split_at + 1][0], cells[-1][1], " ".join(c[2] for c in cells[split_at + 1 :])),
                    ],
                )
            )
        if len(rows) < 3:
            return tables, regions

        index = 0
        while index < len(rows):
            run = [rows[index]]
            cursor = index + 1
            while cursor < len(rows):
                previous_line = run[-1][0]
                candidate_line, _cells = rows[cursor]
                step = candidate_line.bbox[1] - previous_line.bbox[1]
                if 6.0 <= step <= 26.0:
                    run.append(rows[cursor])
                    cursor += 1
                    continue
                break
            if len(run) >= 3:
                # columns must line up across most rows (real table, not a list)
                first_x = [round(cells[0][0] / 12) for _line, cells in run]
                second_x = [round(cells[1][0] / 12) for _line, cells in run]
                stable = max(
                    first_x.count(max(set(first_x), key=first_x.count)),
                    second_x.count(max(set(second_x), key=second_x.count)),
                )
                if stable >= len(run) * 0.6:
                    table_rows = [[cells[0][2], cells[1][2]] for _line, cells in run]
                    if self._reject_pseudo_table(table_rows):
                        index = cursor
                        continue
                    left = min(line.bbox[0] for line, _cells in run)
                    top = min(line.bbox[1] for line, _cells in run)
                    right = max(line.bbox[2] for line, _cells in run)
                    bottom = max(line.bbox[3] for line, _cells in run)
                    # A row whose left cell wraps onto a second line puts its
                    # right-hand value between the two halves, so baseline
                    # grouping never sees a pair and the whole row is dropped —
                    # it then reappears as body text under the table (Table 1 of
                    # the 3DPhenoMVS paper loses its last row exactly this way).
                    absorbed, bottom = self._absorb_table_tail(
                        lines,
                        run,
                        bottom,
                        table_rows,
                        statistics.median(cells[1][0] for _line, cells in run),
                    )
                    table_rows.extend(absorbed)
                    tables.append(
                        RawParagraph(
                            kind_hint="table",
                            table_html=_table_to_html(table_rows),
                            table_rows=table_rows,
                            explicit_bbox=(left, top, right, bottom),
                            flags=["rule-based-table"],
                        )
                    )
                    regions.append((left - 4, top - 4, right + 4, bottom + 4))
                    index = cursor
                    continue
            index += 1
        return tables, regions

    @staticmethod
    def _absorb_table_tail(
        lines: list[RawLine],
        run: list[tuple[RawLine, list[tuple[float, float, str]]]],
        bottom: float,
        existing: list[list[str]],
        right_x: float,
    ) -> tuple[list[list[str]], float]:
        """Rows just below `bottom` that still use the table's own columns.

        Only lines that fit the established two-column shape are absorbed, and if
        anything else sits in the extended band the extension is abandoned — a
        paragraph must never be swallowed by a table region.
        """
        steps = [run[i + 1][0].bbox[1] - run[i][0].bbox[1] for i in range(len(run) - 1)]
        pitch = statistics.median(steps) if steps else 12.0
        candidates = [
            ln for ln in lines
            if bottom - 3.0 <= ln.bbox[1] <= bottom + pitch * 2.4 and (ln.bbox[2] - ln.bbox[0]) > 1
        ]
        if not candidates:
            return [], bottom
        anchors = [ln for ln in candidates if ln.bbox[0] >= right_x - 18.0]
        if not anchors:
            return [], bottom
        absorbed: list[list[str]] = []
        consumed: set[int] = set()
        new_bottom = bottom
        for anchor in sorted(anchors, key=lambda ln: ln.bbox[1]):
            centre = (anchor.bbox[1] + anchor.bbox[3]) / 2.0
            left_parts = [
                ln for ln in candidates
                if ln is not anchor
                and ln.bbox[0] < right_x - 18.0
                and abs((ln.bbox[1] + ln.bbox[3]) / 2.0 - centre) <= pitch * 1.05
            ]
            if not left_parts:
                continue
            text = " ".join(
                ln.text.strip()
                for ln in sorted(left_parts, key=lambda ln: (round(ln.bbox[1], 1), ln.bbox[0]))
                if ln.text.strip()
            )
            if not text:
                continue
            absorbed.append([text, anchor.text.strip()])
            consumed.add(id(anchor))
            consumed.update(id(ln) for ln in left_parts)
            new_bottom = max([new_bottom, anchor.bbox[3]] + [ln.bbox[3] for ln in left_parts])
        if not absorbed:
            return [], bottom
        if any(id(ln) not in consumed for ln in candidates):
            return [], bottom                    # something else lives down there
        if {row[1] for row in existing} & {row[1] for row in absorbed}:
            return [], bottom
        return absorbed, new_bottom + 2.0

    # -- equations ----------------------------------------------------------
    def _insert_equations(
        self, page: pymupdf.Page, page_index: int, paragraphs: list[RawParagraph]
    ) -> list[RawParagraph]:
        """Replace scrambled equation text with a cropped image of the region.

        PDF text extraction returns display equations in a scrambled order —
        subscripts, braces and limits arrive as separate lines — so no amount of
        text post-processing reproduces LaTeX reliably. Cropping keeps the
        equation visually exact, which is also what the reader needs to cite it.

        Equations are found as *bands*: a vertical window holding several
        maths-like lines (including bare fragments such as a lone subscript).
        Single-line detection misses those fragments, which then leak into the
        body as garbled text.
        """
        if not paragraphs:
            return paragraphs

        fragments: list[tuple[float, float, float, float, str]] = []
        for para in paragraphs:
            if para.image_path or para.table_html or not para.lines:
                continue
            text = para.text.strip()
            for line in para.lines:
                line_text = line.text.strip()
                if not line_text:
                    continue
                fragments.append((line.bbox[0], line.bbox[1], line.bbox[2], line.bbox[3], line_text))
        if not fragments:
            return paragraphs
        fragments.sort(key=lambda f: (f[1], f[0]))

        bands: list[list[tuple[float, float, float, float, str]]] = []
        current: list[tuple[float, float, float, float, str]] = []
        for fragment in fragments:
            formula = _looks_like_formula_line(fragment[4])
            if not current:
                if formula:
                    current = [fragment]
                continue
            close_band = (
                fragment[1] - current[-1][1] > 16.0
                or len(current) >= 14
                # a prose line ends the band, but only once the band already has
                # enough maths to be a formula (glyph-only lines sit between them)
                or (
                    not formula
                    and sum(1 for f in current if _looks_like_formula_line(f[4])) >= 3
                )
            )
            if close_band:
                bands.append(current)
                current = [fragment] if formula else []
                continue
            current.append(fragment)
        if current:
            bands.append(current)

        # merge adjacent bands: multi-line equations get split by short prose
        # fragments (older/newer glyph runs) that sit between them
        merged_bands: list[list[tuple[float, float, float, float, str]]] = []
        for band in bands:
            if merged_bands and 0 <= band[0][1] - merged_bands[-1][-1][1] <= 16.0:
                merged_bands[-1].extend(band)
            else:
                merged_bands.append(list(band))
        bands = merged_bands

        regions: list[tuple[float, float, float, float]] = []
        page_width = float(page.rect.width)

        def _region_from(fragment_list: list[tuple[float, float, float, float, str]]):
            if not fragment_list:
                return None
            top = min(f[1] for f in fragment_list)
            bottom = max(f[3] for f in fragment_list)
            # Crop the full width of every line in the band: a display equation is
            # split into several spans (limits, braces) and cropping only the maths
            # fragments cuts the equation in half.
            on_lines = [f for f in fragments if f[1] <= bottom + 2 and f[3] >= top - 2]
            if not on_lines:
                on_lines = fragment_list
            left = min(f[0] for f in on_lines)
            right = max(f[2] for f in on_lines)
            return (left, min(top, min(f[1] for f in on_lines)), right,
                    max(bottom, max(f[3] for f in on_lines)))

        # Each numbered display equation is anchored by its right-aligned "(n)"
        # label: the equation sits on the same baseline (or a few points above), so
        # a vertical window around the label captures exactly that equation —
        # neighbouring equations stay in their own image.
        regions: list[tuple[float, float, float, float]] = []
        numbers = [f for f in fragments if _EQUATION_NUMBER.fullmatch(f[4])]
        numbers.sort(key=lambda f: f[1])
        for number in numbers:
            neighbours = [
                f
                for f in fragments
                if f is not number
                and number[1] - 22 <= f[1] <= number[3] + 6
            ]
            cluster = [
                f for f in neighbours if _looks_like_formula_line(f[4]) or f[0] < number[0]
            ]
            content = cluster or neighbours
            if not content:
                continue
            region = _region_from(content + [number])
            if region is None:
                continue
            left, top, right, bottom = region
            if right - left < 5 or bottom - top < 5:
                continue
            if right - left > page_width * 1.2:
                continue
            # keep adjacent equations as separate images
            if any(
                not (bottom < existing[1] - 3 or top > existing[3] + 3)
                for existing in regions
            ):
                continue
            regions.append((left, top, right, bottom))

        # Fallback for unnumbered displays: dense maths bands with enough content.
        for band in bands:
            if len(band) < 3:
                continue
            formula_lines = sum(1 for f in band if _looks_like_formula_line(f[4]))
            if formula_lines < 3 or formula_lines / len(band) < 0.5:
                continue
            region = _region_from(band)
            if region is None:
                continue
            left, top, right, bottom = region
            if right - left < 5 or bottom - top < 5 or right - left > page_width * 1.2:
                continue
            if any(
                not (bottom < existing[1] - 3 or top > existing[3] + 3)
                for existing in regions
            ):
                continue
            regions.append((left, top, right, bottom))
        if not regions:
            return paragraphs

        kept: list[RawParagraph] = []
        replacements: list[RawParagraph] = []
        used: set[int] = set()
        for para in paragraphs:
            if not para.lines or para.image_path or para.table_html:
                kept.append(para)
                continue
            padded_regions = [
                (region[0] - 10, region[1] - 8, region[2] + 12, region[3] + 8)
                for region in regions
            ]
            # assign per *line*, not per paragraph: the paragraph merger happily
            # glues several equation lines into one tall block, which then fails
            # any whole-block containment test
            inside: list[RawLine] = []
            outside: list[RawLine] = []
            hit_index: Optional[int] = None
            for line in para.lines:
                index = next(
                    (
                        i
                        for i, region in enumerate(padded_regions)
                        if _inside_any(line.bbox, [region], 0.95)
                    ),
                    None,
                )
                if (
                    index is None
                    or _looks_like_section_heading(line.text.strip())
                    # A sentence that merely sits inside the equation band is
                    # body text: it stays in the flow (and out of the crop) even
                    # when the maths around it is replaced by an image.
                    or _reads_like_prose(line.text)
                ):
                    outside.append(line)
                else:
                    inside.append(line)
                    hit_index = index
            if hit_index is None:
                kept.append(para)
                continue
            if outside:
                leftover = copy.copy(para)
                leftover.lines = outside
                leftover.kind_hint = para.kind_hint
                kept.append(leftover)
            if hit_index in used:
                continue                      # this region already produced a crop
            hit = regions[hit_index]
            # Trim the crop to the formula rows so the image does not repeat the
            # prose that shares the band.
            hit = _region_without_prose(hit, fragments) or hit
            padded = (max(0.0, hit[0] - 8), max(0.0, hit[1] - 6), hit[2] + 10, hit[3] + 6)
            name = f"p{page_index + 1:04d}_eq{len(replacements) + 1:03d}.png"
            rel = _crop_region(page, padded, self.asset_key, name)
            if not rel:
                kept.append(RawParagraph(lines=inside))
                continue
            used.add(hit_index)
            replacements.append(
                RawParagraph(
                    kind_hint="formula",
                    image_path=rel,
                    # a synthetic line keeps `bbox` meaningful for layout rules
                    # (an empty block would land at 0,0 and be mistaken for a
                    # running head near the top of the page)
                    lines=[
                        RawLine("", padded, 10.0, False, page_index, 0)  # type: ignore[arg-type]
                    ],
                    explicit_bbox=padded,
                    flags=["equation-image"],
                )
            )
        if replacements:
            self.warnings.append(
                f"page {page_index + 1}: 已把 {len(replacements)} 个公式区域截取为图片"
            )
        return kept + replacements

    # -- figures ------------------------------------------------------------
    def _insert_figures(
        self,
        page: pymupdf.Page,
        page_index: int,
        paragraphs: list[RawParagraph],
        table_rects: list[tuple[float, float, float, float]],
        skip: bool = False,
    ) -> list[RawParagraph]:
        if skip:
            # An OCR'd page is itself one big scanned raster: treating it as a
            # figure would produce a full-page image and nothing else.
            return paragraphs
        images = page.get_image_info(hashes=False) or []
        page_area = max(1.0, float(page.rect.width) * float(page.rect.height))
        added: list[RawParagraph] = []
        existing = [p.bbox for p in paragraphs if p.lines]
        for idx, info in enumerate(images, start=1):
            bbox = tuple(float(v) for v in info.get("bbox", (0, 0, 0, 0)))
            if bbox[2] - bbox[0] < 8 or bbox[3] - bbox[1] < 8:
                continue
            area_ratio = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / page_area
            if area_ratio < settings.figure_min_area_ratio:
                continue
            if any(
                _y_overlap((bbox[0], bbox[2]), (t[0], t[2])) > 0.5 * (bbox[2] - bbox[0])
                and _y_overlap((bbox[1], bbox[3]), (t[1], t[3])) > 0.5 * (bbox[3] - bbox[1])
                for t in table_rects
            ):
                continue
            covered = any(
                _y_overlap((bbox[0], bbox[2]), (e[0], e[2])) > 0.6 * (bbox[2] - bbox[0])
                and _y_overlap((bbox[1], bbox[3]), (e[1], e[3])) > 0.8 * (bbox[3] - bbox[1])
                for e in existing
            )
            if covered:
                continue
            rel = _save_figure(page, bbox, self.asset_key, page_index * 1000 + idx)
            if not rel:
                continue
            added.append(
                RawParagraph(
                    kind_hint="figure",
                    image_path=rel,
                    caption=self._nearest_caption(paragraphs, bbox),
                    lines=[RawLine("", bbox, 10.0, False, page_index)],  # type: ignore[arg-type]
                )
            )
        return paragraphs + added

    @staticmethod
    def _nearest_caption(paragraphs: list[RawParagraph], bbox) -> Optional[str]:
        best: Optional[tuple[float, str]] = None
        for para in paragraphs:
            if para.kind_hint != "caption":
                continue
            pb = para.bbox
            gap = min(abs(pb[1] - bbox[3]), abs(bbox[1] - pb[3]))
            if gap < 90 and (best is None or gap < best[0]):
                best = (gap, para.text)
        return best[1] if best else None

    # -- tables -------------------------------------------------------------
    @staticmethod
    def _find_tables(page: pymupdf.Page):
        try:
            finder = page.find_tables()
            return list(getattr(finder, "tables", []) or [])
        except Exception:
            return []

    @staticmethod
    def _table_rows(table) -> list[list[str]]:
        try:
            extracted = table.extract()
        except Exception:
            return []
        rows: list[list[str]] = []
        for row in extracted or []:
            rows.append([(cell or "").replace("\n", " ").strip() for cell in row])
        return rows

    @staticmethod
    def _looks_like_table(
        rect: tuple[float, float, float, float],
        rows: list[list[str]],
        lines: list[RawLine],
    ) -> bool:
        """Reject false positives: table finders sometimes flag prose blocks.

        A real table has a rectangular grid with mostly short cells; when the
        text inside the candidate region runs full width (i.e. it is prose, such
        as a references column), we decline the region and let it stay text.
        """
        width = rect[2] - rect[0]
        height = rect[3] - rect[1]
        if width < 40 or height < 12:
            return False
        inside = [ln for ln in lines if _inside_any(ln.bbox, [rect], 0.5)]
        if len(inside) >= 3:
            median_width = statistics.median(ln.bbox[2] - ln.bbox[0] for ln in inside)
            if median_width > width * 0.5:
                return False
        cells = [cell for row in rows for cell in row if cell.strip()]
        return len(cells) >= 4

    # -- refinement ---------------------------------------------------------
    @staticmethod
    def _heading_level(para: RawParagraph, median_size: float) -> Optional[int]:
        if para.kind_hint != "heading":
            return None
        size = max((ln.size for ln in para.lines), default=median_size)
        text = para.text
        ratio = size / max(1e-6, median_size)
        if ratio >= 1.6:
            return 1
        if ratio >= 1.25:
            return 2
        match = re.match(r"^\s*(\d{1,2}(?:\.\d{1,2})*)", text)
        if match:
            depth = len(match.group(1).split("."))
            return min(3, max(2, depth))
        return 3 if len(text) < 60 else None

    def _mark_headers_footers(self, blocks: list[Block], page_height: float) -> None:
        for block in blocks:
            text = block.text.strip()
            if not text or block.image_path or block.table_html:
                continue                      # images/tables are never running heads
            # A running head or folio ("5 of 17") must never pollute the outline.
            if _PAGE_NUMBER.match(text) or _FOLIO_ONLY.match(text):
                block.type = "header" if block.bbox.y0 < page_height * 0.5 else "footer"
                continue
            if block.type not in ("text", "formula", "caption", "heading") or len(text) > 80:
                continue
            positioned_header = block.bbox.y1 < page_height * 0.06
            positioned_footer = block.bbox.y0 > page_height * 0.94
            if block.type == "heading" and not (positioned_header or positioned_footer):
                continue
            if positioned_header:
                block.type = "header"
            elif positioned_footer:
                block.type = "footer"

    def _split_glued_headings(self, blocks: list[Block]) -> None:
        """Recover section headings that were glued to the following sentence.

        When the gap between a heading and its paragraph is narrow, the merger
        joins them; the combined line is then too long to be recognised as a
        heading, which silently drops the section from the outline (and makes it
        look like a different font in the reader).
        """
        extra: list[Block] = []
        for block in blocks:
            if block.type not in ("text", "formula") or not block.text:
                continue
            heading, remainder = _split_glued_heading(block.text[:260])
            if not remainder:
                continue
            # the matcher only saw a prefix; rebuild the remainder from the full text
            remainder = block.text[len(heading) :].lstrip()
            if len(remainder) < 20:
                continue
            title = Block(
                id=f"{block.id}-h",
                doc_id=block.doc_id,
                order=block.order,
                page=block.page,
                type="heading",
                text=heading,
                bbox=block.bbox,
                column=block.column,
                size=block.size,
                level=2,
                flags=["split-from-glue"],
            )
            block.text = remainder
            if block.type == "formula":
                block.type = "text"
            extra.append(title)
        if extra:
            blocks.extend(extra)
            blocks.sort(key=lambda b: (b.page, b.bbox.y0, b.id))
            for index, block in enumerate(blocks):
                block.order = index

    def _isolate_rail_splinters(self, blocks: list[Block]) -> None:
        """Pull citation-rail fragments out of body paragraphs.

        When the metadata rail and the body are horizontally interleaved, the
        paragraph merger can glue a rail line onto a body paragraph, producing
        text like "…cultivation research, and Yang, W.; Zhai, R. 3DPhenoMVS: A".
        Such a splinter is moved into its own meta block so it stops interrupting
        the sentence and stops being translated.
        """
        extra: list[Block] = []
        after_references = False
        for block in blocks:
            if block.type == "heading" and re.match(
                r"^\s*(references|bibliography)\s*$", block.text.strip(), re.I
            ):
                after_references = True
                continue
            if after_references:
                continue                      # the reference list is not rail text
            if block.type != "text" or len(block.text) < 10:
                continue
            if _citation_leading(block.text):
                head, tail = _split_at_citation(block.text)
                if not head:
                    # the whole block is rail text
                    block.type = "meta"
                    block.flags = list(block.flags) + ["rail-fragment"]
                    continue
                block.text = head
                suffix = Block(
                    id=f"{block.id}-rail",
                    doc_id=block.doc_id,
                    order=block.order,
                    page=block.page,
                    type="meta",
                    text=tail,
                    bbox=block.bbox,
                    column=block.column,
                    size=block.size,
                    flags=["rail-fragment"],
                )
                extra.append(suffix)
        if extra:
            blocks.extend(extra)
            blocks.sort(key=lambda b: b.order)
            # keep orders unique and monotonic after inserting
            for index, block in enumerate(blocks):
                block.order = index

    def _demote_running_branding(self, blocks: list[Block]) -> None:
        """Mark repeated journal branding that a publisher puts mid-page.

        MDPI repeats "Agronomy 2022, 12, 1865" across the body area, not only in
        the top margin, so the position rule in `_mark_headers_footers` misses
        it. Recurrence plus a small font size is the reliable signal.
        """
        from collections import Counter

        seen = Counter(b.text.strip() for b in blocks if b.type == "text" and 8 <= len(b.text.strip()) <= 60)
        sizes = [b.size for b in blocks if b.type == "text" and b.size > 0]
        if not sizes:
            return
        body_size = statistics.median(sizes)
        for block in blocks:
            if block.type != "text":
                continue
            text = block.text.strip()
            if seen[text] >= 3 and block.size <= body_size * 1.02 and not text.endswith("."):
                block.type = "header"
                block.flags = list(block.flags) + ["running-branding"]

    def _refine_outline(self, blocks: list[Block], title_ids: set[str]) -> None:
        """Drop non-structural entries from the reader's table of contents.

        Journal names, "Research article" rubrics, "TYPE Original Research
        PUBLISHED …" banners and metadata rails all have the *shape* of a
        heading (short, unpunctuated, larger than body text), so text alone does
        not separate them reliably. The evidence that does work:

        * numbered section headings (`1. Introduction`, `2.1. …`) are always kept;
        * the merged document title is always kept;
        * anything else must either be visually larger than the body text, or
          long enough to be a real sentence-like heading — not a rubric.

        The size test only runs when the document actually shows a size
        hierarchy, so flat-but-bold heading styles survive intact.
        """
        sizes = [b.size for b in blocks if b.size > 0 and len(b.text.strip()) >= 12]
        if not sizes:
            return
        body_size = statistics.median(sizes)
        heading_sizes = [b.size for b in blocks if b.type == "heading" and b.size > 0]
        if not heading_sizes:
            return
        has_hierarchy = max(heading_sizes) >= body_size * 1.12
        # Only trust "the outline is exactly the numbered sections" when the
        # document actually uses numbered sections.
        numbered_blocks = [
            b for b in blocks if b.type == "heading" and _looks_like_section_heading(b.text)
        ]
        numbered_count = len(numbered_blocks)
        labeled_outline = numbered_count >= 2
        # Typical size of a really numbered heading: numbered *list items* inside
        # body text are set smaller, which is what separates them from sections.
        numbered_sizes = [b.size for b in numbered_blocks if b.size > 0]
        numbered_size = statistics.median(numbered_sizes) if numbered_sizes else 0.0

        for block in blocks:
            if block.type != "heading" or block.id in title_ids:
                continue
            text = block.text.strip()
            if _looks_like_section_heading(text):
                # A numbered line is a heading only if it looks like the others:
                # numbered *list items* inside body text are set smaller than the
                # document's real numbered headings.
                if (
                    numbered_size
                    and block.level
                    and block.size
                    and block.size < numbered_size * 0.92
                ):
                    block.type = "text"
                    block.level = None
                    block.flags = list(block.flags) + ["outline-demoted"]
                continue
            letters = len(re.findall(r"[A-Za-z\u4e00-\u9fff]", text))
            # Real headings are set larger than the body; a block that is clearly
            # bigger is kept even when it is unnumbered (many papers use
            # "Abstract", "References", "Contents lists available…" as headings).
            clearly_bigger = bool(block.size and block.size >= body_size * 1.3)
            demote = False
            if block.flags and "faint-text" in block.flags:
                demote = True                     # white-on-band journal branding
            elif len(text) < 14 and letters < 12 and block.bbox.y0 < 100:
                # a short letter-poor token in the page's top margin is a running
                # brand ("agronomy", "Heliyon") or a stray glyph ("∑")
                demote = True
            elif _FRONT_MATTER_HEADING.match(text) and not clearly_bigger:
                demote = True                     # publisher banner / rubric
            elif labeled_outline and text.lower() not in _STRUCTURAL_LABELS:
                demote = True
            elif not clearly_bigger and not (
                len(text) >= 15 or letters >= 12 or len(text.split()) >= 3
            ):
                demote = True
            elif (
                has_hierarchy
                and not clearly_bigger
                and len(text) < 55
                and block.size < body_size * 1.05
            ):
                demote = True                     # sits inside the body size band
            elif (
                has_hierarchy
                and not clearly_bigger
                and len(text) < 40
                and block.size < body_size * 1.12
            ):
                demote = True                     # short rubric inside the body band
            if demote:
                block.type = "meta"
                block.level = None
                block.flags = list(block.flags) + ["outline-demoted"]

    def _refine(self, blocks: list[Block]) -> None:
        """Second pass needing the whole document: references section + title."""
        # Type the non-body blocks first: the continuation merge below asks
        # whether a running head sits between two halves, and publishers print
        # those heads in the middle of the page, where only these two passes
        # recognise them.
        self._isolate_rail_splinters(blocks)
        self._demote_running_branding(blocks)
        joined = _join_page_split_paragraphs(blocks) + _join_page_edges(blocks)
        if joined:
            self.warnings.append(f"已把被排版切断的 {joined} 段正文接回同一块")
        ref_start: Optional[int] = None
        title_ids: set[str] = set()
        for i, block in enumerate(blocks):
            text = block.text.strip()
            if len(text) <= 40 and re.match(r"^\s*(references|bibliography)\s*$", text, re.I):
                block.type = "heading"
                block.level = 1
                ref_start = i
                break
        if ref_start is not None:
            for block in blocks[ref_start + 1 :]:
                if block.type not in ("text", "footnote"):
                    continue
                if _REF_START.match(block.text) and re.search(r"\b(19|20)\d{2}\b", block.text):
                    block.type = "reference"
                elif block.text.strip().startswith("[") and re.search(r"\b(19|20)\d{2}\b", block.text):
                    block.type = "reference"

        # Title: the most visually prominent short block near the top of page 1.
        # PDF metadata titles are often empty or wrong, so this is the fallback.
        # A wrapped title arrives as several consecutive headings; they are merged
        # so the outline starts with one title instead of one per line.
        candidates = [
            block
            for block in blocks
            if block.page == 0
            and block.bbox.y0 < 300
            and 20 <= len(block.text.strip()) <= 400
            and block.type in ("text", "heading")
            and "faint-text" not in block.flags
            and not _FRONT_MATTER_HEADING.match(block.text.strip())
        ]
        if candidates:
            top = min(candidates, key=lambda b: b.bbox.y0)
            top.type = "heading"
            top.level = 1
            title_ids = {top.id}
            run = [top]
            for block in blocks:
                if block is top or block.page != 0 or block.type != "heading":
                    continue
                if block.bbox.y0 <= top.bbox.y0 or block.bbox.y0 > 320:
                    continue
                previous = run[-1]
                gap = block.bbox.y0 - previous.bbox.y1
                # display titles use generous leading, so allow up to ~2.5 line
                # heights before deciding the run has ended
                if 0 <= gap < max(12.0, (previous.bbox.y1 - previous.bbox.y0) * 2.5):
                    run.append(block)
            if len(run) > 1:
                run.sort(key=lambda b: b.bbox.y0)
                top = run[0]
                top.text = " ".join(b.text.strip() for b in run if b.text.strip())
                top.bbox = BBox(
                    x0=min(b.bbox.x0 for b in run),
                    y0=min(b.bbox.y0 for b in run),
                    x1=max(b.bbox.x1 for b in run),
                    y1=max(b.bbox.y1 for b in run),
                )
                for block in run[1:]:
                    block.type = "text"
                    block.level = None
                    block.flags = list(block.flags) + ["title-continuation"]
                    title_ids.add(block.id)
                self.warnings.append("已把跨行的论文标题合并为一个标题块")

        self._refine_outline(blocks, title_ids)

        # Only restructure when the publisher actually interleaved front matter
        # with the body — a clean document should keep its original pagination.
        if self.front_matter_hoisted and _interleaves_meta_with_body(blocks):
            _front_matter_first(blocks)

    @staticmethod
    def _dominant_alignment(alignments: Iterable[str]) -> str:
        values = [a for a in alignments if a != "unknown"]
        if not values:
            return "unknown"
        counts: dict[str, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        return max(counts.items(), key=lambda kv: kv[1])[0]


def parse_pdf(
    path: Path, doc_id: str, ocr: bool = False, force_ocr: bool = False
) -> tuple[list[Block], list[PageInfo], ParseReport, dict]:
    return PDFParser(path, doc_id, ocr=ocr, force_ocr=force_ocr).parse()


def file_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
