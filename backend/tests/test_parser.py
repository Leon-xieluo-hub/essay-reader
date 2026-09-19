"""Parser regression tests over generated PDFs.

Run:  python backend/tests/test_parser.py
Synthetic samples are generated into a temporary directory on every run, so the
repository only ships the real-paper fixture and no generated binaries.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Parsing crops figures/equations into the data directory. Point that at a
# throwaway directory so a test run never litters the user's real library.
_TMP_DATA = tempfile.mkdtemp(prefix="essay_reader_tests_")
os.environ["ESSAY_DATA_DIR"] = _TMP_DATA
atexit.register(shutil.rmtree, _TMP_DATA, True)

from app.parsing import parse_pdf  # noqa: E402
from app.parsing.ocr import ocr_status  # noqa: E402
from tests.make_sample import build as build_two_column  # noqa: E402
from tests.make_sample import make_scan_like  # noqa: E402
from tests.make_sample_single import build as build_single  # noqa: E402

# The real published paper stays in the repo (it is the only binary fixture);
# everything synthetic is rebuilt into a scratch directory.
SAMPLES = BACKEND / "tests" / "samples"
WORK = Path(tempfile.mkdtemp(prefix="essay_reader_samples_"))
atexit.register(shutil.rmtree, WORK, True)
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if not condition and detail else ""))
    if not condition:
        FAILURES.append(name)


def ensure_samples() -> tuple[Path, Path]:
    two = WORK / "two_column.pdf"
    single = WORK / "single_column.pdf"
    if not two.exists():
        build_two_column(two, pages=2)
    if not single.exists():
        build_single(single)
    return two, single


def test_two_column(two: Path) -> None:
    blocks, pages, report, meta = parse_pdf(two, "t1")
    check("双栏: 页数正确", len(pages) == 2, f"pages={len(pages)}")
    check("双栏: 识别为双栏", report.alignment == "double", f"alignment={report.alignment}")
    columns = {b.column for b in blocks}
    check("双栏: 存在两栏", columns == {0, 1}, f"columns={columns}")

    # reading order: left column fully precedes right column on page 1
    page0 = [b for b in blocks if b.page == 0]
    left = [b for b in page0 if b.column == 0]
    right = [b for b in page0 if b.column == 1]
    check("双栏: 左右栏都有内容", len(left) >= 4 and len(right) >= 4, f"L={len(left)} R={len(right)}")
    check(
        "双栏: 阅读顺序先左后右",
        max(b.order for b in left) < min(b.order for b in right),
        "left/right orders interleave",
    )

    tables = [b for b in blocks if b.type == "table"]
    check("双栏: 表格被结构化还原", bool(tables), "no table block")
    if tables:
        rows = tables[0].table_rows or []
        check("双栏: 表头正确", rows and rows[0][0] == "Model", f"rows={rows[:1]}")
        check("双栏: 表格行数完整", len(rows) == 5, f"rows={len(rows)}")

    check("双栏: 提取到标题层级", any(b.type == "heading" and b.level for b in blocks))
    check("双栏: 页脚被识别", any(b.type == "footer" for b in blocks))
    check("双栏: 乱码率为 0", report.garbage_ratio == 0.0, f"garbage={report.garbage_ratio}")
    # Regression: block ids used to restart per page, so multi-page documents
    # overwrote earlier pages in the primary key and lost almost all content.
    ids = {b.id for b in blocks}
    check("双栏: 块 ID 全局唯一", len(ids) == len(blocks), f"{len(ids)} unique of {len(blocks)}")
    check("双栏: 每页都有块", len({b.page for b in blocks}) == len(pages))
    check(
        "双栏: order 与索引一致",
        [b.order for b in blocks] == list(range(len(blocks))),
    )


def test_single_column(single: Path) -> None:
    blocks, pages, report, meta = parse_pdf(single, "t2")
    check("单栏: 识别为单栏", report.alignment == "single", f"alignment={report.alignment}")
    check("单栏: 没有跨栏误判", {b.column for b in blocks} == {0}, f"columns={{b.column for b in blocks}}")
    check("单栏: 段落数合理", report.paragraph_count >= 8, f"paragraphs={report.paragraph_count}")
    check("单栏: 段落合并不碎", len(blocks) < 40, f"blocks={len(blocks)}")
    tables = [b for b in blocks if b.type == "table"]
    check("单栏: 表格被识别", bool(tables), "no table block")
    references = [b for b in blocks if b.type == "reference"]
    check("单栏: 参考文献被识别", len(references) >= 1, f"references={len(references)}")
    check("单栏: 无序的空白页", all(p.block_count > 0 for p in pages))
    ids = {b.id for b in blocks}
    check("单栏: 块 ID 全局唯一", len(ids) == len(blocks), f"{len(ids)} unique of {len(blocks)}")


def test_ocr_fallback(two: Path) -> None:
    """A rasterised page has no text layer, so only OCR can read it."""
    available, detail = ocr_status()
    if not available:
        print(f"[SKIP] OCR: {detail}")
        return

    scan = WORK / "scanned.pdf"
    if not scan.exists():
        make_scan_like(two, scan, page_index=0)

    without = parse_pdf(scan, "ocr-off", ocr=False)[2]
    check("OCR: 关闭时确实无文本层", without.paragraph_count == 0, f"paragraphs={without.paragraph_count}")

    blocks, pages, report, meta = parse_pdf(scan, "ocr-on", ocr=True)
    check("OCR: 走 OCR 通道", report.channel == "ocr", f"channel={report.channel}")
    check("OCR: 记录了处理页数", report.ocr_pages == 1, f"ocr_pages={report.ocr_pages}")
    check("OCR: 置信度合理", report.ocr_confidence >= 0.8, f"confidence={report.ocr_confidence}")
    check("OCR: 提取到正文段落", report.paragraph_count >= 6, f"paragraphs={report.paragraph_count}")

    text = " ".join(b.text for b in blocks)
    for needle in ("Sparse Attention", "Introduction", "Method"):
        check(f"OCR: 识别出 {needle!r}", needle.lower() in text.lower())
    check("OCR: 识别出数字", "87.6" in text or "81.3" in text, f"digits missing in: {text[:120]}")
    check("OCR: 质量分体现不确定性", report.quality_score < 100, f"score={report.quality_score}")
    check(
        "OCR: 不把整页扫描图当成插图",
        all(b.type != "figure" for b in blocks),
        "figure block present on an OCR'd page",
    )
    check("OCR: 有提示用户核对", any("OCR" in w for w in report.warnings))


def test_real_world_layout() -> None:
    """Regression for the failure modes a real MDPI-style paper exposed.

    The fixture is a real published article (17 pages, single column, running
    heads, numbered sections). It caught three distinct bugs: paragraphs
    shattering into one block per line, a running head ("5 of 17") entering the
    outline, and measurement text being read as a section heading.
    """
    fixture = SAMPLES / "real_world_3dphenomvs.pdf"
    if not fixture.exists():
        print(f"[SKIP] 真实样本缺失：{fixture.name}")
        return

    import re

    blocks, pages, report, meta = parse_pdf(fixture, "real")
    check("真实样本: 页数", len(pages) == 17, f"pages={len(pages)}")

    page5 = [b for b in blocks if b.page == 4 and b.type in ("text", "caption", "heading")]
    check("真实样本: 第 5 页不再碎成一行一块", len(page5) <= 12, f"page5 blocks={len(page5)}")
    paragraph_lengths = sorted(len(b.text) for b in page5 if b.type == "text")
    median = paragraph_lengths[len(paragraph_lengths) // 2] if paragraph_lengths else 0
    check("真实样本: 第 5 页段落长度正常", median >= 60, f"median={median}")

    # the sentence that spans the fragment boundary must be intact
    page5_text = " ".join(b.text for b in page5)
    check(
        "真实样本: 跨块句子完整",
        "conducted from two different viewpoints" in page5_text
        and "at the top. Then, it was placed" in page5_text,
    )

    headings = [b for b in blocks if b.type == "heading"]
    check("真实样本: 有结构化标题", len(headings) >= 15, f"headings={len(headings)}")
    check(
        "真实样本: 页码不进目录",
        not any(re.match(r"^\d+\s+of\s+\d+$", h.text.strip()) for h in headings),
        "running head leaked into the outline",
    )
    check(
        "真实样本: 测量数值不当标题",
        not any(re.match(r"^0\.\d", h.text.strip()) for h in headings),
        "measurement read as heading",
    )
    check(
        "真实样本: 目录包含主要章节",
        {"1. Introduction", "2. Materials and Methods", "3. Results"}.issubset(
            {h.text.strip() for h in headings}
        ),
        f"headings={[h.text[:24] for h in headings][:8]}",
    )
    # A heading glued to the sentence that follows it must still reach the
    # outline: this one starts with a digit ("2.8. 3D Point Cloud …") and was
    # dropped both because of the glue and because of the leading digit.
    check(
        "真实样本: 数字开头的章节进入目录",
        any(h.text.strip().startswith("2.8.") for h in headings),
        f"headings={[h.text[:22] for h in headings if h.text.strip().startswith('2.')]}",
    )
    # Journal branding repeats inside the body area, not only in the top margin.
    branding = [b for b in blocks if "running-branding" in b.flags]
    check("真实样本: 页中期刊名被移出正文", len(branding) >= 5, f"branding={len(branding)}")
    # Citation-rail splinters must not interrupt a body sentence.
    rail = [b for b in blocks if "rail-fragment" in b.flags]
    check("真实样本: 引文栏碎片被单独成块", bool(rail), f"rail={len(rail)}")
    check(
        "真实样本: 正文不再含引文栏碎片",
        not any(
            b.type == "text" and re.search(r"Yang, W\.|Zhai, R\.", b.text) for b in blocks
        ),
    )
    # Outline hygiene: publisher branding and rubrics must not appear, and no
    # entry may be a short single token ("agronomy", "Winter", "Heliyon").
    junk = [
        h.text.strip()
        for h in headings
        if len(h.text.strip()) < 9
        or h.text.strip().lower() in {"agronomy", "heliyon", "winter", "summer"}
        or re.match(r"^\d+\s*(of|/)\s*\d+$", h.text.strip())
        or re.match(r"^0\.\d", h.text.strip())
    ]
    check("真实样本: 目录无品牌/跑头/碎词", not junk, f"junk={junk}")

    # Front matter ("Citation:", "Received:", "Keywords:") must be its own type
    # so it can be shown outside the body flow instead of interrupting it.
    meta = [b for b in blocks if b.type == "meta"]
    check("真实样本: 前沿信息被识别为 meta", len(meta) >= 5, f"meta={len(meta)}")
    meta_text = " | ".join(b.text for b in meta)
    check(
        "真实样本: meta 含关键标签",
        any(label in meta_text for label in ("Citation:", "Received:", "Keywords:")),
        f"meta sample={meta_text[:80]}",
    )
    check(
        "真实样本: meta 不参与段落计数",
        all(b.type != "meta" for b in blocks if b.text.strip().startswith("[1]")),
    )

    # Table 1 in this paper has horizontal rules but no vertical grid, so the
    # generic table finder misses it; it must still be reconstructed.
    tables = [b for b in blocks if b.type == "table"]
    check("真实样本: 无框线表格被还原", bool(tables), "no table block")
    if tables:
        header = tables[0].table_rows[0] if tables[0].table_rows else []
        check(
            "真实样本: 表格表头正确",
            header[:2] == ["Trait", "Abbreviation"],
            f"header={header}",
        )
        check(
            "真实样本: 表格行数完整",
            len(tables[0].table_rows or []) >= 15,
            f"rows={len(tables[0].table_rows or [])}",
        )

    # Display equations come back scrambled from the text layer, so they are
    # cropped as images instead of being pasted as garbage text.
    equations = [b for b in blocks if b.image_path and "equation" in " ".join(b.flags)]
    check("真实样本: 公式被截取为图片", bool(equations), f"equations={len(equations)}")
    from app.config import ASSET_DIR

    check(
        "真实样本: 公式图片文件确实落盘",
        bool(equations) and all((ASSET_DIR / b.image_path).exists() for b in equations),
        f"missing={[b.image_path for b in equations if not (ASSET_DIR / b.image_path).exists()]}",
    )
    import re as _re

    leftover = [
        b
        for b in blocks
        if b.type in ("text", "formula")
        and _re.search(r"[=∈∑∥]", b.text)
        and _re.search(r"∥|∑|∈", b.text)
    ]
    check("真实样本: 没有残留的公式乱码块", len(leftover) <= 1, f"leftover={[b.text[:30] for b in leftover]}")

    # --- segmentation defects reported from the running app -------------------
    # (1) two independent paragraphs were merged into one text block;
    # (2) one paragraph split by a page break became two blocks on two pages.
    from app.parsing.pdf_parser import _ends_mid_sentence

    split_tails = []
    for index in range(len(pages)):
        tail = [b for b in blocks if b.page == index and b.type == "text"]
        if tail and _ends_mid_sentence(tail[-1].text):
            split_tails.append((index + 1, tail[-1].text[-50:]))
    check(
        "真实样本: 跨页段落已在页末接续",
        len(split_tails) <= 1,
        f"mid-sentence page tails={split_tails}",
    )

    rejoined = 0
    for probe in (
        "convex set that contains all the points",
        "leaf detection and",
        "differences due",
    ):
        hit = next((b for b in blocks if probe in b.text), None)
        if hit is not None and len(hit.text) > 200:
            rejoined += 1
    check("真实样本: 被分页切断的句子合回同一块", rejoined >= 3, f"rejoined={rejoined}")

    seen: dict[str, int] = {}
    duplicates = 0
    for block in blocks:
        if block.type == "text" and len(block.text) > 80:
            head = block.text[:60]
            if head in seen:
                duplicates += 1
            seen[head] = block.page
    check("真实样本: 跨页接续没有产生重复文本", duplicates == 0, f"duplicates={duplicates}")

    # Over-merge guard: an indented first line starts a new paragraph even with
    # uniform leading, so the paragraph count must stay in a plausible band
    # instead of collapsing (too few) or shattering (too many).
    check(
        "真实样本: 段落数在合理区间",
        80 <= report.paragraph_count <= 160,
        f"paragraphs={report.paragraph_count}",
    )
    check("真实样本: 块数在合理区间", 140 <= len(blocks) <= 240, f"blocks={len(blocks)}")

    # text must not be lost while re-blocking. Display equations are deliberately
    # rendered as cropped images (their text layer is scrambled), so the textual
    # coverage sits slightly below 100% whenever equations exist.
    import pymupdf

    doc = pymupdf.open(fixture)
    raw = sum(len(re.sub(r"\s+", "", doc[i].get_text())) for i in range(doc.page_count))
    doc.close()
    extracted = sum(len(re.sub(r"\s+", "", b.text)) for b in blocks)
    ratio = extracted / max(1, raw)
    has_equation_images = any(
        b.image_path and "equation" in " ".join(b.flags) for b in blocks
    )
    floor = 0.96 if has_equation_images else 0.99
    check(
        f"真实样本: 文本覆盖率 >= {floor:.0%}",
        ratio >= floor,
        f"coverage={ratio:.3f} equation_images={has_equation_images}",
    )


def main() -> int:
    two, single = ensure_samples()
    test_two_column(two)
    test_single_column(single)
    test_ocr_fallback(two)
    test_real_world_layout()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} 项失败: {', '.join(FAILURES)}")
        return 1
    print("解析器测试全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
