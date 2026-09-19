"""Smoke tests for the parsing-adjacent core: protection, chunking, IR schema.

Run with:  python backend/tests/smoke.py      (from the repo root)
No network and no LLM required.
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

# Keep test runs out of the user's data directory (config creates it on import).
_TMP_DATA = tempfile.mkdtemp(prefix="essay_reader_smoke_")
os.environ["ESSAY_DATA_DIR"] = _TMP_DATA
atexit.register(shutil.rmtree, _TMP_DATA, True)

from app.schemas import BBox, Block  # noqa: E402
from app.services.protect import mask, unmask, validate  # noqa: E402
from app.services.translate import chunk_blocks, select_blocks  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def test_protection_roundtrip() -> None:
    source = (
        "As shown in Fig. 3 and Table 2, the model reaches 91.5% accuracy "
        "(Smith et al., 2020), improving on prior work [12,13]. See doi:10.1000/xyz for details."
    )
    masked = mask(source)
    check("mask: 图号被保护", "Fig. 3" not in masked.text and "figref" in masked.counts)
    check("mask: 引用被保护", "[12,13]" not in masked.text)
    check("mask: DOI 被保护", "10.1000/xyz" not in masked.text)
    check("mask: 占位符数量 > 0", len(masked.tokens) >= 4, f"tokens={masked.tokens}")

    restored, issues = unmask(masked.text, masked)
    check("unmask: 完全还原", restored == source, f"got={restored!r}")
    check("unmask: 无告警", issues == [], f"issues={issues}")


def test_validation_catches_losses() -> None:
    source = "Table 3 reports 0.87 F1 on the SQuAD dataset [4]."
    masked = mask(source)

    dropped, _ = unmask(masked.text.replace('<ph id="0"/>', "").replace('<ph id="1"/>', ""), masked)
    problems = validate(source, masked, dropped)
    check("validate: 能发现占位符丢失", len(problems) > 0, f"problems={problems}")

    digits_lost = validate(source, masked, "该表报告了很高的分数。")
    check("validate: 能发现数字丢失", any("数字" in p for p in digits_lost), f"problems={digits_lost}")

    check("validate: 空译文被判失败", validate(source, masked, "") == ["译文为空"])

    # Placeholder ids are ours, not the paper's: they must not be counted as
    # numbers, or a paragraph with nine protected tokens looks like nine numbers.
    heavy = mask("The 3D model of the 2D view was trained in 2020 with 16 images.")
    check(
        "validate: 占位符编号不算数字",
        validate(
            "The 3D model of the 2D view was trained in 2020 with 16 images.",
            heavy,
            "该三维模型于 2020 年用 16 张图像训练完成。",
        )
        == [],
        f"problems={validate('x', heavy, '该三维模型于 2020 年用 16 张图像训练完成。')}",
    )

    good = unmask(masked.text, masked)[0]
    check("validate: 正常译文通过", validate(source, masked, "表 3 报告 0.87 F1 [4]。") == [])
    check(
        "validate: 英文目标仍检查图号丢失",
        any("figref" in p for p in validate(source, masked, "The table reports 0.87 [4].", "en")),
    )
    check(
        "validate: 中文目标不误报图号",
        not any("figref" in p for p in validate(source, masked, "该表报告 0.87 [4]。", "zh")),
    )


def test_extract_json_tolerance() -> None:
    from app.providers import extract_json

    check("json: 裸 JSON", extract_json('{"a":1}') == {"a": 1})
    check("json: 代码块包裹", extract_json('```json\n{"a":2}\n```') == {"a": 2})
    check("json: 前后有解释文字", extract_json('好的，结果如下：{"a":3} 以上。') == {"a": 3})
    try:
        extract_json("完全没有 JSON")
        check("json: 无 JSON 时报错", False)
    except Exception:
        check("json: 无 JSON 时报错", True)


def _block(index: int, text: str, kind: str = "text") -> Block:
    return Block(
        id=f"doc-b{index:05d}",
        doc_id="doc",
        order=index,
        page=index // 4,
        type=kind,  # type: ignore[arg-type]
        text=text,
        bbox=BBox(x0=0, y0=0, x1=100, y1=20),
    )


def test_chunking_and_selection() -> None:
    blocks = [_block(i, "word " * 200) for i in range(8)]
    chunks = chunk_blocks(blocks, budget=300)
    check("chunk: 按预算切分", len(chunks) >= 3, f"chunks={len(chunks)}")
    check("chunk: 不丢块", sum(len(c) for c in chunks) == len(blocks))

    mixed = blocks + [
        _block(20, "", "header"),
        _block(21, "  ", "text"),
        _block(22, "Figure 1 caption", "caption"),
    ]
    selected = select_blocks(mixed)
    ids = {b.id for b in selected}
    check("select: 跳过页眉", "doc-b00020" not in ids)
    check("select: 跳过空段落", "doc-b00021" not in ids)
    check("select: 保留图注", "doc-b00022" in ids)

    only = select_blocks(mixed, ["doc-b00003"])
    check("select: 支持指定段落", len(only) == 1 and only[0].id == "doc-b00003")

    noise = [
        _block(30, "5. 6. 7. 8. 9. 10. 11. 12."),
        _block(31, "https://example.org/paper/12345"),
        _block(32, "Table 1. 3D point cloud accuracy"),
    ]
    noise_ids = {b.id for b in select_blocks(noise)}
    check("select: 跳过纯编号列表", "doc-b00030" not in noise_ids)
    check("select: 跳过纯链接行", "doc-b00031" not in noise_ids)
    check("select: 保留含文字的图注", "doc-b00032" in noise_ids)


def test_protection_of_technical_tokens() -> None:
    # Digit+letter tokens used to be masked digit-first ("<ph id=0/>D"), and a
    # model that reflowed the tag left a stray "3" in the Chinese sentence.
    source = "The 3D point cloud of the 3DPhenoMVS pipeline covers 400 m2 in 2020."
    masked = mask(source)
    check(
        "mask: 3D 不再是 数字+字母 的半个占位符",
        'id="0"/>D' not in masked.text,
        f"masked={masked.text!r}",
    )
    check(
        "mask: 3D 保护成一个占位符",
        masked.tokens.count("3D") == 1,
        f"tokens={masked.tokens}",
    )
    check(
        "mask: 不拆开 3DPhenoMVS 这类词内数字",
        "3DPhenoMVS" in masked.text,
        f"masked={masked.text!r}",
    )
    restored, issues = unmask(masked.text, masked)
    check("unmask: 技术标记原样还原", restored == source, f"got={restored!r}")
    check("unmask: 无告警", issues == [], f"issues={issues}")

    dated = mask("Seedlings were transplanted on 1 February 2020 (accessed on 29 June 2022).")
    check(
        "mask: 日期被整体保护",
        "date" in dated.counts and dated.tokens.count("1 February 2020") == 1,
        f"tokens={dated.tokens}",
    )


def test_token_estimate() -> None:
    from app.providers import estimate_tokens

    en = estimate_tokens("The quick brown fox jumps over the lazy dog. " * 10)
    zh = estimate_tokens("这是一段中文测试文本，用来估计 token 数量。" * 10)
    check("tokens: 英文估算合理", 80 <= en <= 160, f"en={en}")
    check("tokens: 中文估算更高", zh > en, f"en={en} zh={zh}")


def main() -> int:
    test_protection_roundtrip()
    test_validation_catches_losses()
    test_extract_json_tolerance()
    test_chunking_and_selection()
    test_protection_of_technical_tokens()
    test_token_estimate()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} 项失败: {', '.join(FAILURES)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
