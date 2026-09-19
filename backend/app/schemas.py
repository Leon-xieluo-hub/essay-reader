"""Document IR (intermediate representation) schemas.

One flat, offset-addressed block list keeps the API simple and lets the
frontend virtualize; `order` defines reading order, `(page, bbox)` defines
where the block lives on the original page so the PDF view can highlight it.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

BlockType = Literal[
    "heading",
    "text",
    "figure",
    "table",
    "formula",
    "reference",
    "footnote",
    "caption",
    "meta",
    "header",
    "footer",
]

Alignment = Literal["single", "double", "mixed", "unknown"]


class BBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float

    def as_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]


class Block(BaseModel):
    id: str
    doc_id: str
    order: int
    page: int
    type: BlockType
    text: str = ""
    bbox: BBox
    column: int = 0
    level: Optional[int] = None          # heading level, 1..6
    size: float = 0.0                    # dominant font size, for outline checks
    # figure / formula payloads
    image_path: Optional[str] = None
    latex: Optional[str] = None
    caption: Optional[str] = None
    caption_block_id: Optional[str] = None
    # table payload
    table_html: Optional[str] = None
    table_rows: Optional[list[list[str]]] = None
    table_rows_translated: Optional[list[list[str]]] = None
    # quality flags raised by the parser
    flags: list[str] = Field(default_factory=list)


class PageInfo(BaseModel):
    index: int
    width: float
    height: float
    rotation: int = 0
    block_count: int = 0


class ParseReport(BaseModel):
    """Parser self-check, surfaced in the UI as a quality indicator."""

    text_coverage: float = 0.0
    garbage_ratio: float = 0.0
    table_count: int = 0
    figure_count: int = 0
    formula_count: int = 0
    paragraph_count: int = 0
    alignment: Alignment = "unknown"
    channel: str = "text-layer"
    ocr_pages: int = 0
    ocr_confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    duration_ms: int = 0

    @property
    def quality_score(self) -> float:
        score = 100.0
        score -= min(40.0, self.garbage_ratio * 400.0)
        score -= 0.0 if self.paragraph_count else 30.0
        score -= 0.0 if self.text_coverage > 0.02 else 25.0
        # OCR text is a best-effort reconstruction: degrade the score so the UI
        # never presents it as equal to a clean text layer.
        if self.ocr_pages:
            score -= min(20.0, 4.0 + 0.06 * self.ocr_pages)
            if self.ocr_confidence and self.ocr_confidence < 0.85:
                score -= min(15.0, (0.85 - self.ocr_confidence) * 60.0)
        score -= 5.0 * len(self.warnings)
        return max(0.0, min(100.0, score))


class DocumentMeta(BaseModel):
    id: str
    filename: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    page_count: int = 0
    file_size: int = 0
    sha256: str = ""
    created_at: str = ""
    status: str = "parsed"
    parse_report: Optional[ParseReport] = None


class Document(DocumentMeta):
    pages: list[PageInfo] = Field(default_factory=list)


class BlockOut(BaseModel):
    """Block payload returned to the client, with translations attached."""

    id: str
    order: int
    page: int
    type: BlockType
    text: str
    bbox: BBox
    column: int = 0
    level: Optional[int] = None
    size: float = 0.0
    image_url: Optional[str] = None
    latex: Optional[str] = None
    caption: Optional[str] = None
    table_html: Optional[str] = None
    table_rows: Optional[list[list[str]]] = None
    table_rows_translated: Optional[list[list[str]]] = None
    flags: list[str] = Field(default_factory=list)
    translations: dict[str, str] = Field(default_factory=dict)
    translation_meta: dict[str, TranslationMeta] = Field(default_factory=dict)
    note_count: int = 0


class TranslationMeta(BaseModel):
    provider: str
    model: str
    lang: str
    quality: str = "ok"          # ok | suspect | failed | manual
    attempts: int = 1
    tokens_in: int = 0
    tokens_out: int = 0


BlockOut.model_rebuild()


class TranslateRequest(BaseModel):
    doc_id: str
    provider: Literal["local", "cloud"] = "local"
    lang: str = "zh"
    style: Literal["academic", "literal"] = "academic"
    block_ids: Optional[list[str]] = None      # None = whole document
    force: bool = False                        # ignore cache


class SummaryRequest(BaseModel):
    doc_id: str
    provider: Literal["local", "cloud"] = "local"
    lang: str = "zh"
    force: bool = False


class AskRequest(BaseModel):
    doc_id: str
    question: str
    provider: Literal["local", "cloud"] = "local"
    lang: str = "zh"
    block_ids: Optional[list[str]] = None
    top_k: int = 6


class NoteIn(BaseModel):
    doc_id: str
    block_id: str
    quote: str = ""
    comment: str = ""
    color: str = "yellow"


class Note(BaseModel):
    id: int
    doc_id: str
    block_id: str
    quote: str
    comment: str
    color: str
    created_at: str


class GlossaryTermIn(BaseModel):
    source: str
    target: str
    note: str = ""


class GlossaryTerm(GlossaryTermIn):
    id: int
    doc_id: str
    locked: bool = False


class ProviderStatus(BaseModel):
    name: str
    available: bool
    detail: str = ""
    model: str = ""
    base_url: str = ""
    is_local: bool = False
    installed_models: list[str] = Field(default_factory=list)


class UsageStats(BaseModel):
    cloud_tokens_in: int = 0
    cloud_tokens_out: int = 0
    cloud_estimated_cost_cny: float = 0.0
    local_blocks_translated: int = 0
    local_seconds: float = 0.0


class TaskState(BaseModel):
    id: str
    doc_id: str
    kind: str                    # translate | summary | parse
    provider: str = ""
    status: str = "running"      # running | done | error | cancelled
    total: int = 0
    done: int = 0
    message: str = ""
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
