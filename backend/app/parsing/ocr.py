"""Local, offline OCR engine for scanned PDFs.

Uses RapidOCR (ONNX, CPU) when available. Everything runs on-device: no image
leaves the machine and no network is required after the ONNX models are
installed. The engine is a process-wide singleton because model loading costs
~1s and the models are a few hundred MB of RAM.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

import pymupdf

from app.config import settings

_engine_lock = threading.Lock()
_engine = None
_engine_error = ""


@dataclass
class OcrLine:
    text: str
    bbox: tuple[float, float, float, float]      # PDF page coordinates
    confidence: float


@dataclass
class OcrPage:
    lines: list[OcrLine]
    mean_confidence: float


def _build_engine():
    """Instantiate RapidOCR with conservative CPU threading.

    OCR runs on CPU while a local LLM may occupy the GPU, so we cap the thread
    count to avoid starving translation and to keep the two stages from
    competing for the same machine.
    """
    from rapidocr import RapidOCR

    params: dict = {"Global.with_onnx": True}
    if settings.ocr_num_threads > 0:
        params.update(
            {
                "EngineConfig.onnxruntime.intra_op_num_threads": settings.ocr_num_threads,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            }
        )
    try:
        return RapidOCR(params=params)
    except Exception:
        return RapidOCR()


def get_engine():
    """Return the shared OCR engine, or None when OCR is unavailable."""
    global _engine, _engine_error
    if not settings.ocr_enabled:
        _engine_error = "OCR 已在配置中关闭"
        return None
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        try:
            _engine = _build_engine()
            _engine_error = ""
        except Exception as exc:  # missing dependency, broken model files…
            _engine_error = f"{type(exc).__name__}: {exc}"
            return None
    return _engine


def ocr_status() -> tuple[bool, str]:
    engine = get_engine()
    if engine is None:
        return False, _engine_error or "OCR 引擎不可用"
    return True, "RapidOCR（本地离线）"


def _to_pdf_bbox(points, zoom: float) -> tuple[float, float, float, float]:
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return (
        min(xs) / zoom,
        min(ys) / zoom,
        max(xs) / zoom,
        max(ys) / zoom,
    )


def ocr_page(page: pymupdf.Page, dpi: Optional[int] = None) -> OcrPage:
    """Run OCR over one page and return lines in PDF coordinates."""
    engine = get_engine()
    if engine is None:
        return OcrPage(lines=[], mean_confidence=0.0)

    render_dpi = dpi or settings.ocr_dpi
    zoom = render_dpi / 72.0
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    image = _pixmap_to_array(pixmap)
    if image is None:
        return OcrPage(lines=[], mean_confidence=0.0)

    output = engine(image)
    texts = getattr(output, "txts", None)
    boxes = getattr(output, "boxes", None)
    scores = getattr(output, "scores", None)
    if not texts:
        return OcrPage(lines=[], mean_confidence=0.0)

    lines: list[OcrLine] = []
    confidences: list[float] = []
    for index, text in enumerate(texts):
        cleaned = " ".join(str(text).split())
        if not cleaned:
            continue
        box = boxes[index] if boxes is not None and index < len(boxes) else None
        if box is None:
            continue
        confidence = (
            float(scores[index]) if scores is not None and index < len(scores) else 1.0
        )
        if confidence < settings.ocr_min_confidence:
            continue
        lines.append(
            OcrLine(text=cleaned, bbox=_to_pdf_bbox(box, zoom), confidence=confidence)
        )
        confidences.append(confidence)

    mean = sum(confidences) / len(confidences) if confidences else 0.0
    return OcrPage(lines=lines, mean_confidence=mean)


def _pixmap_to_array(pixmap: pymupdf.Pixmap):
    try:
        import numpy as np
    except Exception:
        return None
    # PyMuPDF gives RGB(A); RapidOCR wants BGR for colour images.
    array = np.frombuffer(pixmap.samples, dtype=np.uint8)
    channels = pixmap.n
    try:
        array = array.reshape(pixmap.height, pixmap.width, channels)
    except ValueError:
        return None
    if channels == 4:
        return array[:, :, :3][:, :, ::-1].copy()
    if channels == 3:
        return array[:, :, ::-1].copy()
    if channels == 1:
        return np.repeat(array, 3, axis=2)
    return None


def page_needs_ocr(page: pymupdf.Page, text_length: int, image_coverage: float) -> bool:
    """Heuristic: a page with almost no text but a large raster area is scanned."""
    if text_length >= settings.ocr_min_text_chars:
        return False
    return image_coverage >= 0.35


def image_coverage(page: pymupdf.Page) -> float:
    """Fraction of the page covered by embedded raster images."""
    try:
        info = page.get_image_info(hashes=False) or []
    except Exception:
        return 0.0
    page_area = max(1.0, float(page.rect.width) * float(page.rect.height))
    covered = 0.0
    for item in info:
        bbox = item.get("bbox")
        if not bbox:
            continue
        covered += max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
    return min(1.0, covered / page_area)
