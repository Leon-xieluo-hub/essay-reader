"""Generate a two-column academic-looking PDF for parser verification.

Run:  python backend/tests/make_sample.py [output.pdf]

The layout deliberately includes the hard parts: a full-width title band, a
two-column body with a wide gutter, a caption under an embedded figure, a
three-line table, an equation-ish paragraph, a references section and a footer
page number. It is generated, so it contains no copyrighted material.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

PAGE_W, PAGE_H = 595.0, 842.0          # A4 in points
MARGIN = 56.0
GUTTER = 26.0
COL_W = (PAGE_W - 2 * MARGIN - GUTTER) / 2
LEFT_X = MARGIN
RIGHT_X = MARGIN + COL_W + GUTTER

TITLE = "Sparse Attention Routing for Long-Context Document Understanding"
AUTHORS = "L. Zhang, M. Okafor, and R. Tanaka"

ABSTRACT = (
    "Transformer models degrade on documents longer than a few thousand tokens because "
    "self-attention cost grows quadratically. We introduce Sparse Attention Routing (SAR), "
    "a routing layer that learns which token blocks may attend to each other, reducing "
    "attention cost from O(n^2) to O(n log n) while keeping accuracy. On the LongDoc benchmark "
    "SAR improves F1 from 81.3 to 87.6 and reduces inference latency by 2.4x."
)

LEFT = [
    ("1  Introduction", "heading"),
    ("Reading scientific documents requires reasoning over tables, figures and equations that are "
     "spread across dozens of pages [1,2]. Standard transformers attend to every pair of tokens, "
     "which becomes prohibitively expensive: a 64k-token document needs 4.1 billion attention "
     "entries per layer, as shown in Table 1.", "body"),
    ("Prior work reduces cost with fixed sparsity patterns such as sliding windows or random "
     "blocks (Smith et al., 2022). We argue that the sparsity pattern should be learned per "
     "document, not fixed in advance, because the useful connections depend on layout and "
     "discourse structure.", "body"),
    ("2  Method", "heading"),
    ("2.1  Routing layer", "subheading"),
    ("Each token block b_i is embedded and scored against a small set of learned anchors. The "
     "router keeps the top-k anchors per block and masks all other attention entries. We set "
     "k = 4 for all experiments and use a temperature of 0.7 during training.", "body"),
    ("The routing weights are differentiable with a straight-through estimator, so the model can "
     "be trained end to end. The extra parameters add only 1.2% to the total model size.", "body"),
    ("Equation 1 gives the resulting attention score for a query q at position p, where A is the "
     "anchor matrix and sigma is the softmax temperature: score(q) = max over anchors in A of "
     "sigma(q . a / T).", "formula"),
    ("2.2  Implementation", "subheading"),
    ("We implement SAR in PyTorch and train on 8 A100 GPUs for 72 hours. Block size is 64 tokens; "
     "documents are truncated at 65,536 tokens and packed with a document-level attention mask.", "body"),
]

RIGHT = [
    ("3  Experiments", "heading"),
    ("We evaluate on LongDoc, which contains 12,400 documents with an average length of 18,300 "
     "tokens, and on NarrativeQA for transfer. Baselines are Longformer, BigBird and a full "
     "attention model trained with gradient checkpointing.", "body"),
    ("Table 1 reports F1, memory and latency. SAR reaches 87.6 F1 while using 41% of the memory "
     "of full attention, and remains within 0.4 F1 of the full model on NarrativeQA.", "body"),
    ("Figure 1 shows the learned routing pattern for a three-page document. Anchors concentrate on "
     "section headers and table captions, which matches the intuition that structural cues carry "
     "most of the long-range signal.", "body"),
    ("4  Ablations", "heading"),
    ("Removing the routing temperature hurts F1 by 2.1 points; replacing learned anchors with "
     "random anchors costs 5.8 points. Increasing k beyond 6 gives no measurable benefit while "
     "raising latency by 19%.", "body"),
    ("5  Conclusion", "heading"),
    ("Learned sparse routing makes long-document transformers practical without sacrificing "
     "quality. Future work will extend SAR to multi-modal inputs where figures and tables are "
     "encoded jointly with text.", "body"),
]

TABLE_ROWS = [
    ["Model", "F1", "Memory (GB)", "Latency (ms)"],
    ["Full attention", "88.0", "72.4", "412"],
    ["Longformer", "83.7", "31.2", "268"],
    ["BigBird", "84.9", "33.8", "291"],
    ["SAR (ours)", "87.6", "29.7", "172"],
]

REFERENCES = [
    "[1] Smith, J., Lee, K. Sparse attention revisited. In ICML, 2022.",
    "[2] Okafor, M., Zhang, L. Layout-aware retrieval for scientific QA. In ACL, 2023.",
    "[3] Tanaka, R., et al. Long-document benchmarks. Journal of NLP, 2024.",
]


def wrap(text: str, font_size: float, width: float, font: str = "helv") -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pymupdf.get_text_length(candidate, fontname=font, fontsize=font_size) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_paragraph(
    page: pymupdf.Page,
    text: str,
    x: float,
    y: float,
    width: float,
    font_size: float = 9.2,
    bold: bool = False,
    leading: float = 12.2,
) -> float:
    font = "hebo" if bold else "helv"
    for line in wrap(text, font_size, width, font):
        if y > PAGE_H - MARGIN - 18:
            break
        page.insert_text((x, y), line, fontname=font, fontsize=font_size)
        y += leading
    return y


def draw_figure(page: pymupdf.Page, x: float, y: float, width: float) -> float:
    """A simple vector 'routing map' that renders as an image-less drawing."""
    height = 110.0
    page.draw_rect(pymupdf.Rect(x, y, x + width, y + height), color=(0.25, 0.25, 0.25), width=0.8)
    cols, rows = 12, 6
    cell_w = width / cols
    cell_h = height / rows
    for row in range(rows):
        for col in range(cols):
            if (row * 7 + col * 3) % 5 != 0:
                continue
            rect = pymupdf.Rect(
                x + col * cell_w + 1.5,
                y + row * cell_h + 1.5,
                x + (col + 1) * cell_w - 1.5,
                y + (row + 1) * cell_h - 1.5,
            )
            page.draw_rect(rect, color=(0.85, 0.78, 0.4), fill=(0.96, 0.9, 0.62), width=0.4)
    return y + height


def draw_table(page: pymupdf.Page, x: float, y: float, width: float) -> float:
    row_h = 14.0
    col_count = len(TABLE_ROWS[0])
    col_ws = [width * 0.34, width * 0.16, width * 0.26, width * 0.24]
    top = y
    for r_index, row in enumerate(TABLE_ROWS):
        cursor = x
        for c_index, cell in enumerate(row):
            rect = pymupdf.Rect(cursor, y, cursor + col_ws[c_index], y + row_h)
            page.draw_rect(rect, color=(0.35, 0.35, 0.35), width=0.6)
            page.insert_text(
                (cursor + 3, y + 10),
                cell,
                fontname="hebo" if r_index == 0 else "helv",
                fontsize=8.2,
            )
            cursor += col_ws[c_index]
        # three-line style: heavier rule under the header
        if r_index == 0:
            page.draw_line(
                pymupdf.Point(x, y + row_h), pymupdf.Point(x + width, y + row_h), width=1.1
            )
        y += row_h
    return y + 6


def build(path: Path, pages: int = 2) -> None:
    doc = pymupdf.open()
    for page_index in range(pages):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)

        if page_index == 0:
            y = MARGIN + 6
            for line in wrap(TITLE, 17, PAGE_W - 2 * MARGIN, "hebo"):
                page.insert_text((MARGIN, y), line, fontname="hebo", fontsize=17)
                y += 21
            page.insert_text((MARGIN, y + 2), AUTHORS, fontname="helv", fontsize=10)
            y += 20
            y = draw_paragraph(page, ABSTRACT, MARGIN, y + 4, PAGE_W - 2 * MARGIN, 9.0)
            page.draw_line(
                pymupdf.Point(MARGIN, y + 4), pymupdf.Point(PAGE_W - MARGIN, y + 4), width=0.7
            )
            left_y = y + 20
        else:
            left_y = MARGIN

        # left column
        ly = left_y
        for text, kind in LEFT if page_index == 0 else []:
            if kind in ("heading", "subheading"):
                ly += 4
                ly = draw_paragraph(page, text, LEFT_X, ly, COL_W, 10.4 if kind == "heading" else 9.6, True)
                ly += 1.5
            else:
                ly = draw_paragraph(page, text, LEFT_X, ly, COL_W)
                ly += 5.5

        if page_index == 1:
            ly = draw_paragraph(page, "6  References", LEFT_X, ly + 4, COL_W, 10.4, True)
            ly += 2
            for ref in REFERENCES:
                ly = draw_paragraph(page, ref, LEFT_X, ly, COL_W, 8.6, leading=11.2)
                ly += 2.5

        # right column
        ry = left_y
        for text, kind in RIGHT if page_index == 0 else []:
            if kind == "heading":
                ry += 4
                ry = draw_paragraph(page, text, RIGHT_X, ry, COL_W, 10.4, True)
                ry += 1.5
            else:
                ry = draw_paragraph(page, text, RIGHT_X, ry, COL_W)
                ry += 5.5

        if page_index == 1:
            ry = draw_paragraph(
                page,
                "Table 1: Results on the LongDoc benchmark (higher F1 is better).",
                RIGHT_X,
                ry + 6,
                COL_W,
                8.6,
                leading=11.2,
            )
            ry = draw_table(page, RIGHT_X, ry + 8, COL_W)
            ry = draw_paragraph(
                page,
                "Figure 1: Learned routing pattern over a three-page document; anchors cluster on "
                "section headers and table captions.",
                RIGHT_X,
                ry + 26,
                COL_W,
                8.6,
                leading=11.2,
            )
            ry = draw_figure(page, RIGHT_X, ry + 8, COL_W)

        # header + footer
        page.insert_text((MARGIN, 36), "Preprint · generated sample for parser testing", fontsize=7.5)
        page.insert_text((PAGE_W / 2 - 4, PAGE_H - 40), str(page_index + 1), fontsize=9)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()
    print(f"wrote {path}")


def make_scan_like(source: Path, target: Path, page_index: int = 0, degrade: bool = True) -> None:
    """Rasterise one page of `source` so the result has no text layer.

    Used to exercise the OCR fallback: the output looks like a scan (a single
    full-page image, optionally rotated slightly and lightened) while we still
    know exactly what the text should be.
    """
    src = pymupdf.open(source)
    page = src[page_index]
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(200 / 72.0, 200 / 72.0), alpha=False)
    image_bytes = pixmap.tobytes("png")
    width, height = page.rect.width, page.rect.height
    src.close()

    out = pymupdf.open()
    new_page = out.new_page(width=width, height=height)
    if degrade:
        # slight offset + grey wash: closer to a real scanner than a clean raster
        new_page.insert_image(
            pymupdf.Rect(6, 5, width - 4, height - 6),
            stream=image_bytes,
        )
        new_page.draw_rect(
            pymupdf.Rect(0, 0, width, height),
            color=None,
            fill=(0.94, 0.94, 0.92),
            fill_opacity=0.18,
            overlay=True,
        )
    else:
        new_page.insert_image(pymupdf.Rect(0, 0, width, height), stream=image_bytes)

    target.parent.mkdir(parents=True, exist_ok=True)
    out.save(target)
    out.close()
    print(f"wrote {target} (scan-like, page {page_index + 1})")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("backend/tests/samples/two_column.pdf")
    build(target, pages=2)
