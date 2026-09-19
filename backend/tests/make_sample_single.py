"""Generate a single-column PDF (thesis style) for parser verification.

Run:  python backend/tests/make_sample_single.py [output.pdf]
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

PAGE_W, PAGE_H = 595.0, 842.0
MARGIN = 72.0
BODY_W = PAGE_W - 2 * MARGIN

TITLE = "Retrieval-Augmented Summarisation of Scientific Articles"
AUTHORS = "A. Nowak and P. Ivanov"

ABSTRACT = (
    "We study retrieval-augmented summarisation for scientific articles. Our system first selects "
    "evidence spans with a sparse retriever, then conditions a sequence-to-sequence model on the "
    "selected spans. On the SciSumm benchmark we improve ROUGE-L from 34.1 to 38.7 while using 40% "
    "fewer parameters than the strongest baseline."
)

SECTIONS = [
    ("1 Introduction", "heading"),
    ("Scientific articles are long, dense and structured. Summarisation systems must decide which "
     "sections matter, and a single encoder pass over a 20-page article is both slow and lossy. "
     "Retrieval offers a natural remedy: select a small set of evidence spans, then summarise only "
     "those.", "body"),
    ("Prior work applies retrieval to question answering; we show it transfers to summarisation when "
     "the retriever is trained with a summary-level objective rather than a token-level one.", "body"),
    ("2 Method", "heading"),
    ("We split each article into 200-token spans with 40-token overlap. A BM25 index over spans is "
     "built once per article. The summariser is a 770M-parameter encoder-decoder trained with a "
     "combined cross-entropy and coverage loss.", "body"),
    ("At inference we retrieve the top 24 spans, rerank them with a cross-encoder, and pack them into "
     "a 4,096-token context. The model then generates a summary of at most 320 tokens.", "body"),
    ("3 Results", "heading"),
    ("Table 1 reports ROUGE-L on SciSumm and on arXivSum. Our method improves ROUGE-L from 34.1 to "
     "38.7 on SciSumm and from 29.4 to 31.8 on arXivSum, with no increase in inference cost relative "
     "to the dense baseline.", "body"),
    ("Ablations show that removing the coverage loss costs 1.9 ROUGE-L, and replacing the "
     "cross-encoder reranker with BM25 ordering costs 2.4.", "body"),
    ("4 Discussion", "heading"),
    ("Retrieval does not merely shorten the input; it also changes what the model attends to. We "
     "observe that summaries produced with retrieval contain more numeric results and fewer generic "
     "motivational sentences.", "body"),
    ("5 Conclusion", "heading"),
    ("Retrieval-augmented summarisation is a practical route to better scientific summaries at lower "
     "cost. Future work will study multi-document settings.", "body"),
]

TABLE_ROWS = [
    ["Dataset", "Baseline", "Ours", "Params"],
    ["SciSumm", "34.1", "38.7", "770M"],
    ["arXivSum", "29.4", "31.8", "770M"],
]

REFERENCES = [
    "[1] Nowak, A. Sparse retrieval for summarisation. In EMNLP, 2023.",
    "[2] Ivanov, P., Chen, Y. Evidence packing strategies. In NAACL, 2024.",
]


def wrap(text: str, size: float, width: float, font: str = "helv") -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pymupdf.get_text_length(candidate, fontname=font, fontsize=size) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw(
    page: pymupdf.Page,
    text: str,
    y: float,
    width: float = BODY_W,
    size: float = 10.0,
    bold: bool = False,
    leading: float = 14.0,
    x: float = MARGIN,
) -> float:
    font = "hebo" if bold else "helv"
    for line in wrap(text, size, width, font):
        if y > PAGE_H - MARGIN:
            break
        page.insert_text((x, y), line, fontname=font, fontsize=size)
        y += leading
    return y


def build(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)

    y = MARGIN + 8
    y = draw(page, TITLE, y, BODY_W, 16, True, 20)
    y = draw(page, AUTHORS, y + 6, BODY_W, 10.5)
    y = draw(page, ABSTRACT, y + 10, BODY_W, 9.4, leading=13.0)
    page.draw_line(pymupdf.Point(MARGIN, y + 4), pymupdf.Point(PAGE_W - MARGIN, y + 4), width=0.7)
    y += 22

    for text, kind in SECTIONS:
        if kind == "heading":
            y = draw(page, text, y + 6, BODY_W, 11.5, True, 15)
        else:
            y = draw(page, text, y, BODY_W, 10.0, leading=14.0)
            y += 6

    y = draw(page, "Table 1: ROUGE-L on two benchmarks.", y + 10, BODY_W, 9.0, leading=12)
    row_h = 15.0
    col_ws = [BODY_W * 0.3, BODY_W * 0.24, BODY_W * 0.24, BODY_W * 0.22]
    for r_index, row in enumerate(TABLE_ROWS):
        cursor = MARGIN
        for c_index, cell in enumerate(row):
            rect = pymupdf.Rect(cursor, y, cursor + col_ws[c_index], y + row_h)
            page.draw_rect(rect, color=(0.35, 0.35, 0.35), width=0.6)
            page.insert_text((cursor + 4, y + 11), cell, fontname="hebo" if r_index == 0 else "helv", fontsize=9)
            cursor += col_ws[c_index]
        y += row_h
    y += 14

    y = draw(page, "6 References", y, BODY_W, 11.5, True, 15)
    for ref in REFERENCES:
        y = draw(page, ref, y, BODY_W, 9.0, leading=12) + 3

    page.insert_text((MARGIN, 40), "Preprint · single-column parser sample", fontsize=7.5)
    page.insert_text((PAGE_W / 2 - 4, PAGE_H - 40), "1", fontsize=9)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()
    print(f"wrote {path}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("backend/tests/samples/single_column.pdf")
    build(target)
