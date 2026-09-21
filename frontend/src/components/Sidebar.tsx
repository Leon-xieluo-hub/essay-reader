import { useMemo, useRef } from "react";

import { navigate } from "../hooks/useHashRoute";
import { useT } from "../i18n";
import { useApp } from "../store";
import { UploadDropzone } from "./UploadDropzone";

export function Sidebar() {
  const t = useT();
  const open = useApp((s) => s.sidebarOpen);
  const toggle = useApp((s) => s.toggleSidebar);
  const documents = useApp((s) => s.documents);
  const doc = useApp((s) => s.doc);
  const blocks = useApp((s) => s.blocks);
  const activeBlockId = useApp((s) => s.activeBlockId);
  const scrolledBlockId = useApp((s) => s.scrolledBlockId);
  const setActiveBlock = useApp((s) => s.setActiveBlock);
  const removeDocument = useApp((s) => s.removeDocument);
  const exporting = useRef(false);

  const toc = useMemo(
    () => blocks.filter((block) => block.type === "heading" && (block.text || "").trim()),
    [blocks],
  );

  if (!open) {
    return (
      <div className="flex w-9 shrink-0 flex-col items-center gap-2 border-r border-line bg-paper-2/60 py-3">
        <button className="btn btn-ghost !px-1.5" onClick={toggle} title={t("展开侧栏")}>
          ›
        </button>
      </div>
    );
  }

  // The outline belongs to the open paper, so it is rendered directly under that
  // paper's card instead of after the whole library (it used to sit below every
  // document, which meant scrolling past the entire library to reach it).
  const outline = (active: boolean) =>
    active && toc.length > 0 ? (
      <div className="mb-2 max-h-[42vh] overflow-y-auto rounded-xl border border-line bg-surface/60 px-2 py-1.5">
        <div className="px-1 py-1 text-[11px] font-medium tracking-wide text-ink-2">{t("目录")}</div>
        {toc.map((heading) => {
          const level = heading.level ?? 2;
          const current = activeBlockId === heading.id || scrolledBlockId === heading.id;
          return (
            <button
              key={heading.id}
              className={`block w-full truncate rounded-lg py-1 pr-2 text-left text-[12.5px] transition ${
                current ? "bg-accent text-ink" : "text-ink-2 hover:bg-surface"
              }`}
              style={{ paddingLeft: `${8 + (level - 1) * 12}px` }}
              onClick={() => {
                exporting.current = false;
                setActiveBlock(heading.id);
                document
                  .getElementById(`block-${heading.id}`)
                  ?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
              title={heading.text}
            >
              {heading.text}
            </button>
          );
        })}
      </div>
    ) : null;

  return (
    <aside className="flex w-[268px] shrink-0 flex-col border-r border-line bg-paper-2/60">
      <div className="flex items-center justify-between px-3 py-2">
        <span className="text-xs font-medium tracking-wide text-ink-2">{t("文献库")}</span>
        <button className="btn btn-ghost !px-1.5" onClick={toggle} title={t("折叠侧栏")}>
          ‹
        </button>
      </div>

      <div className="px-3">
        <UploadDropzone compact />
      </div>

      <div className="mt-2 min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {documents.length === 0 && (
          <p className="px-2 py-6 text-center text-xs leading-relaxed text-ink-3">
            {t("还没有文献。")}
            <br />
            {t("拖入 PDF 或点击上方按钮开始。")}
          </p>
        )}
        {documents.map((item) => {
          const active = doc?.id === item.id;
          return (
            <div key={item.id}>
              <div
                className={`group mb-1 rounded-xl border px-2.5 py-2 transition ${
                  active ? "border-accent-strong bg-accent-soft" : "border-transparent hover:bg-surface"
                }`}
              >
                <button
                  className="w-full text-left"
                  onClick={() => navigate(`#/doc/${item.id}`)}
                  title={item.title || item.filename}
                >
                  <div className="truncate text-sm font-medium">{item.title || item.filename}</div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-1 text-[11px] text-ink-3">
                    <span>{t("{count} 页", { count: item.page_count })}</span>
                    {item.parse_report && (
                      <span className="chip !py-0 !text-[10px]">
                        {t(
                          item.parse_report.alignment === "double"
                            ? "双栏"
                            : item.parse_report.alignment === "single"
                              ? "单栏"
                              : "混排",
                        )}
                      </span>
                    )}
                    {item.parse_report && item.parse_report.figure_count > 0 && (
                      <span className="chip !py-0 !text-[10px]">
                        {t("图 {count}", { count: item.parse_report.figure_count })}
                      </span>
                    )}
                    {item.parse_report && item.parse_report.table_count > 0 && (
                      <span className="chip !py-0 !text-[10px]">
                        {t("表 {count}", { count: item.parse_report.table_count })}
                      </span>
                    )}
                  </div>
                </button>
                <div className="mt-1 hidden justify-end group-hover:flex">
                  <button
                    className="btn btn-ghost !px-1.5 !py-0.5 !text-[11px] text-danger"
                    onClick={() => {
                      if (
                        confirm(
                          t("删除《{name}》及其译文与笔记？", {
                            name: item.title || item.filename,
                          }),
                        )
                      ) {
                        void removeDocument(item.id);
                      }
                    }}
                  >
                    {t("删除")}
                  </button>
                </div>
              </div>
              {outline(active)}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
