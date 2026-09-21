import { memo, useMemo, useState } from "react";
import katex from "katex";

import type { DocBlock } from "../api/types";
import { useT } from "../i18n";
import { useApp, type ReadingMode } from "../store";

interface Props {
  block: DocBlock;
  mode: ReadingMode;
  lang: string;
  search: string;
  active: boolean;
  onActivate: () => void;
  onRetranslate: () => void;
}

export const BlockView = memo(function BlockView({
  block,
  mode,
  search,
  active,
  onActivate,
  onRetranslate,
}: Props) {
  const openLightbox = useApp((s) => s.openLightbox);
  const setDockTab = useApp((s) => s.setDockTab);
  const [adding, setAdding] = useState(false);
  const [comment, setComment] = useState("");
  const addNote = useApp((s) => s.addNote);
  const provider = useApp((s) => s.provider);
  const t = useT();

  const translation = block.translations[provider] || Object.values(block.translations)[0] || "";
  const meta = block.translation_meta[provider];
  const quality = meta?.quality;

  const highlight = useMemo(() => (text: string) => markText(text, search), [search]);
  const richOriginal = useMemo(
    () => renderEmphasis(block.text, block.emphasis, highlight),
    [block.text, block.emphasis, highlight],
  );

  // --------------------------------------------------------------- equations
  // Cropped equation images are the reliable representation: the PDF text layer
  // returns subscripts and limits in a scrambled order, so rendering that text
  // would show garbage. The original text stays available for search/copy.
  if (block.type === "formula" && block.image_url) {
    return (
      <figure
        id={`block-${block.id}`}
        className={`para my-3 px-1 py-1 ${active ? "para-active" : ""}`}
        onClick={(event) => {
          event.stopPropagation();
          onActivate();
        }}
      >
        <button
          className="block w-full"
          title={
            block.text
              ? t("原文文本：{text}", { text: block.text.slice(0, 120) })
              : t("公式原图")
          }
          onClick={(event) => {
            event.stopPropagation();
            openLightbox(block.image_url as string, block.text.slice(0, 200));
          }}
        >
          <img
            src={block.image_url}
            alt="equation"
            loading="lazy"
            className="mx-auto max-h-[220px] rounded-lg border border-line bg-surface object-contain px-2 py-1"
          />
        </button>
        <figcaption className="mt-1 text-center text-[11px] text-ink-3">
          {t("公式按原版面截取（文本层顺序错乱，故不做文字重排）")}
        </figcaption>
      </figure>
    );
  }

  // --------------------------------------------------- front matter / sidebar
  if (block.type === "meta") {
    return (
      <div
        id={`block-${block.id}`}
        className={`para my-3 rounded-xl border border-line bg-paper-2/60 px-3 py-2 ${
          active ? "para-active" : ""
        }`}
        style={{ fontFamily: "var(--font-sans)" }}
        onClick={(event) => {
          event.stopPropagation();
          onActivate();
        }}
      >
        <div className="mb-1 flex items-center gap-2 text-[11px] text-ink-3">
          <span className="chip">{t("文章信息")}</span>
          <span>{t("非正文内容（出版商元信息栏）")}</span>
        </div>
        <p className="text-[0.85em] leading-relaxed text-ink-2">{highlight(block.text)}</p>
      </div>
    );
  }

  // ---------------------------------------------------------------- figures
  if (block.type === "figure") {
    return (
      <figure
        id={`block-${block.id}`}
        className={`para my-5 px-1 py-1 ${active ? "para-active" : ""}`}
        onClick={(event) => {
          event.stopPropagation();
          onActivate();
        }}
      >
        {block.image_url ? (
          <button
            className="block w-full"
            onClick={(event) => {
              event.stopPropagation();
              openLightbox(block.image_url as string, block.caption || "");
            }}
          >
            <img
              src={block.image_url}
              alt={block.caption || "figure"}
              loading="lazy"
              className="mx-auto max-h-[520px] rounded-xl border border-line bg-surface object-contain"
            />
          </button>
        ) : (
          <div className="rounded-xl border border-dashed border-line-2 p-6 text-center text-xs text-ink-3">
            {t("该区域疑似图片但未能裁切，请切换到「原版页」查看")}
          </div>
        )}
        {(block.caption || translation) && (
          <figcaption className="mt-2 text-center text-[0.85em] leading-relaxed text-ink-2">
            {block.caption && <span>{highlight(block.caption)}</span>}
            {translation && (
              <div className="mt-1 text-ink" style={{ fontFamily: "var(--font-serif)" }}>
                {highlight(translation)}
              </div>
            )}
          </figcaption>
        )}
      </figure>
    );
  }

  // ----------------------------------------------------------------- tables
  if (block.type === "table") {
    // In translated / bilingual mode show the translated grid, keeping the
    // original available underneath so numbers and units can be cross-checked.
    const translatedRows = block.table_rows_translated;
    const showTranslated = mode !== "original" && Boolean(translatedRows?.length);
    const primaryRows = showTranslated ? (translatedRows as string[][]) : block.table_rows;
    const showPair =
      mode === "bilingual" && Boolean(translatedRows?.length) && Boolean(block.table_rows?.length);
    const renderGrid = (rows: string[][], dim: boolean) => (
      <div className={`overflow-x-auto rounded-xl border border-line bg-surface ${dim ? "opacity-80" : ""}`}>
        <table className="doc-table">
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) =>
                  rowIndex === 0 ? (
                    <th key={cellIndex}>{highlight(cell)}</th>
                  ) : (
                    <td key={cellIndex}>{highlight(cell)}</td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );

    return (
      <div
        id={`block-${block.id}`}
        className={`para my-5 px-1 py-1 ${active ? "para-active" : ""}`}
        onClick={(event) => {
          event.stopPropagation();
          onActivate();
        }}
      >
        <div className="mb-1 flex items-center gap-2 text-[11px] text-ink-3">
          <span className="chip">{t("表格")}</span>
          <span>
            {showTranslated
              ? t("已按行列翻译 · 可与原表对照")
              : t("解析为结构化数据，可横向滚动")}
          </span>
          <button className="btn btn-ghost !px-1.5 !py-0.5 !text-[11px]" onClick={onRetranslate}>
            {t("重译此表")}
          </button>
        </div>
        {primaryRows?.length ? (
          <div className="space-y-2">
            {renderGrid(primaryRows, false)}
            {showPair && (
              <details className="text-[11px] text-ink-3">
                <summary className="cursor-pointer">{t("查看原表（未翻译）")}</summary>
                <div className="mt-1">{renderGrid(block.table_rows as string[][], true)}</div>
              </details>
            )}
          </div>
        ) : (
          <div
            className="rounded-xl border border-line bg-surface p-3"
            dangerouslySetInnerHTML={{ __html: block.table_html || "" }}
          />
        )}
      </div>
    );
  }

  // ------------------------------------------------------------------- text
  const isHeading = block.type === "heading";
  const level = Math.min(6, Math.max(1, block.level ?? 2));
  const headingClass =
    level === 1
      ? "mt-8 mb-3 text-[1.5em] font-semibold"
      : level === 2
        ? "mt-7 mb-2 text-[1.22em] font-semibold"
        : "mt-5 mb-1.5 text-[1.06em] font-semibold";

  const showOriginal = mode === "original" || mode === "bilingual";
  const showTranslation = mode === "translated" || mode === "bilingual";
  const quoted = block.type === "reference" || block.type === "footnote";

  const body = (
    <>
      {showOriginal && block.type !== "formula" && (
        <p className={isHeading ? "" : "text-ink"}>{richOriginal}</p>
      )}
      {block.type === "formula" && (
        <FormulaBlock text={block.text} latex={block.latex} highlight={highlight} />
      )}
      {showTranslation && translation && (
        <p
          className={`${showOriginal && !isHeading ? "mt-1.5 border-l-2 border-accent-strong pl-3 text-ink-2" : ""}`}
        >
          {highlight(translation)}
        </p>
      )}
      {showTranslation && !translation && provider !== "off" && (
        <p className="mt-1 text-[0.85em] text-ink-3">{t("（尚未翻译 · 悬停段落可单段翻译）")}</p>
      )}
    </>
  );

  if (isHeading) {
    return (
      <div
        id={`block-${block.id}`}
        className={`para ${headingClass} ${active ? "para-active" : ""}`}
        onClick={(event) => {
          event.stopPropagation();
          onActivate();
        }}
        onDoubleClick={onRetranslate}
      >
        {body}
      </div>
    );
  }

  return (
    <div
      id={`block-${block.id}`}
      className={`para para-hover group my-2.5 px-2 py-1.5 ${
        active ? "para-active" : quality === "suspect" ? "para-suspect" : quality === "failed" ? "para-failed" : ""
      } ${quoted ? "text-[0.9em] text-ink-2" : ""}`}
      onClick={(event) => {
        event.stopPropagation();
        onActivate();
      }}
    >
      {body}

      <div className="mt-1 hidden items-center gap-1.5 text-[11px] text-ink-3 group-hover:flex">
        <span>{t("第 {page} 页", { page: block.page + 1 })}</span>
        {quality === "suspect" && (
          <span className="chip chip-warn" title={t("质量校验未通过（数字/引用/占位符不一致），建议核对")}>
            {t("待复核")}
          </span>
        )}
        {quality === "failed" && <span className="chip chip-danger">{t("翻译失败")}</span>}
        <button className="btn btn-ghost !px-1.5 !py-0.5 !text-[11px]" onClick={onRetranslate}>
          {t("重译")}
        </button>
        <button
          className="btn btn-ghost !px-1.5 !py-0.5 !text-[11px]"
          onClick={() => setAdding((value) => !value)}
        >
          {t("笔记")}
        </button>
        <button
          className="btn btn-ghost !px-1.5 !py-0.5 !text-[11px]"
          onClick={() => setDockTab("chat")}
        >
          {t("就此提问")}
        </button>
      </div>

      {adding && (
        <div className="mt-2 rounded-xl border border-line bg-paper-2 p-2">
          <textarea
            className="textarea"
            rows={2}
            placeholder={t("写点批注…（会保存到本地）")}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
          />
          <div className="mt-1.5 flex justify-end gap-2">
            <button className="btn" onClick={() => setAdding(false)}>
              {t("取消")}
            </button>
            <button
              className="btn btn-primary"
              onClick={() => {
                void addNote(block.id, block.text.slice(0, 240), comment || t("（无批注）"));
                setComment("");
                setAdding(false);
              }}
            >
              {t("保存")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
});

function FormulaBlock({
  text,
  latex,
  highlight,
}: {
  text: string;
  latex: string | null;
  highlight: (value: string) => React.ReactNode;
}) {
  const t = useT();
  const rendered = useMemo(() => {
    if (!latex) return null;
    try {
      return katex.renderToString(latex, { throwOnError: false, displayMode: true });
    } catch {
      return null;
    }
  }, [latex]);

  if (rendered) {
    return <div className="my-2 overflow-x-auto" dangerouslySetInnerHTML={{ __html: rendered }} />;
  }
  return (
    <p className="my-2 rounded-lg bg-paper-2 px-3 py-2 font-mono text-[0.92em]">
      {highlight(text)}
      <span className="ml-2 chip">{t("公式原文（可切原版页核对）")}</span>
    </p>
  );
}

/** Render a block's text with the bold/italic runs the PDF carried. */
export function renderEmphasis(
  text: string,
  emphasis: { start: number; end: number; style: string }[] | undefined,
  highlight: (value: string) => React.ReactNode,
): React.ReactNode {
  if (!emphasis || emphasis.length === 0) return highlight(text);
  const runs = [...emphasis]
    .filter((run) => run.start < run.end && run.start < text.length)
    .sort((a, b) => a.start - b.start);
  if (!runs.length) return highlight(text);
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  for (const [index, run] of runs.entries()) {
    const start = Math.max(run.start, cursor);
    const end = Math.min(run.end, text.length);
    if (end <= start) continue;
    if (start > cursor) {
      nodes.push(<span key={`plain-${index}`}>{highlight(text.slice(cursor, start))}</span>);
    }
    const inner = run.style.includes("italic")
      ? <em>{highlight(text.slice(start, end))}</em>
      : highlight(text.slice(start, end));
    nodes.push(
      <strong key={`emph-${index}`} className="font-semibold">
        {inner}
      </strong>,
    );
    cursor = end;
  }
  if (cursor < text.length) {
    nodes.push(<span key="tail">{highlight(text.slice(cursor))}</span>);
  }
  return nodes;
}

/** Wrap search hits in <mark> without dangerouslySetInnerHTML. */
export function markText(text: string, needle: string): React.ReactNode {  const query = needle.trim();
  if (!query) return text;
  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  let index = lowerText.indexOf(lowerQuery);
  let key = 0;
  while (index !== -1) {
    if (index > cursor) parts.push(text.slice(cursor, index));
    parts.push(
      <mark className="hit" key={key++}>
        {text.slice(index, index + query.length)}
      </mark>,
    );
    cursor = index + query.length;
    index = lowerText.indexOf(lowerQuery, cursor);
  }
  parts.push(text.slice(cursor));
  return parts;
}
