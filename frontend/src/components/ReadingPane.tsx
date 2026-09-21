import { useEffect, useLayoutEffect, useRef } from "react";

import { useT } from "../i18n";
import { useApp } from "../store";

import { BlockView } from "./BlockView";

export function ReadingPane() {
  const t = useT();
  const blocks = useApp((s) => s.blocks);
  const mode = useApp((s) => s.mode);
  const fontScale = useApp((s) => s.fontScale);
  const lang = useApp((s) => s.lang);
  const search = useApp((s) => s.search);
  const activeBlockId = useApp((s) => s.activeBlockId);
  const setActiveBlock = useApp((s) => s.setActiveBlock);
  const setScrolledBlock = useApp((s) => s.setScrolledBlock);
  const setScrollAnchor = useApp((s) => s.setScrollAnchor);
  const storedAnchor = useApp((s) => s.scrollAnchorId);
  const translateBlock = useApp((s) => s.translateBlock);
  const searchIndex = useApp((s) => s.searchIndex);
  const searchHits = useApp((s) => s.searchHits);
  const anchorRef = useRef<string | null>(null);

  const visible = blocks.filter((block) => block.type !== "header" && block.type !== "footer");
  // Front matter (article info / citation / keywords rails) is shown as its own
  // block above the body so it never interrupts a sentence.
  const leadingMeta: typeof visible = [];
  for (const block of visible) {
    if (block.type === "meta") leadingMeta.push(block);
    else break;
  }
  const body = visible.slice(leadingMeta.length);

  // scroll-spy: remember which paragraph is under the reading line
  useEffect(() => {
    const container = document.getElementById("reading-scroll");
    if (!container) return;
    const onScroll = () => {
      const top = container.getBoundingClientRect().top + 120;
      let current: string | null = null;
      let anchor: string | null = null;
      for (const block of body) {
        const element = document.getElementById(`block-${block.id}`);
        if (!element) continue;
        if (element.getBoundingClientRect().top <= top) current = block.id;
        else break;
      }
      // the first paragraph at/after the viewport top is what a mode switch has
      // to keep in place: bilingual → translation-only changes every block's
      // height, and the browser would otherwise clamp the scroll position
      for (const block of body) {
        const element = document.getElementById(`block-${block.id}`);
        if (!element) continue;
        if (element.getBoundingClientRect().top >= container.getBoundingClientRect().top - 4) {
          anchor = block.id;
          break;
        }
      }
      if (anchor) anchorRef.current = anchor;
      if (anchor) setScrollAnchor(anchor);
      if (current) setScrolledBlock(current);
    };
    container.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => container.removeEventListener("scroll", onScroll);
  }, [body, setScrolledBlock, setScrollAnchor]);

  // Switching 双语 / 译文 / 原文 rewrites every block, so keep the paragraph the
  // reader was looking at pinned to the top instead of jumping to the beginning.
  // The anchor lives in the store because the original-page view unmounts this
  // component, and coming back should not drop the reader at the top either.
  useLayoutEffect(() => {
    const container = document.getElementById("reading-scroll");
    const id = anchorRef.current ?? storedAnchor;
    if (!container || !id) return;
    const element = document.getElementById(`block-${id}`);
    if (!element) return;
    anchorRef.current = id;
    const delta =
      element.getBoundingClientRect().top - container.getBoundingClientRect().top - 12;
    if (Math.abs(delta) > 1) container.scrollTop += delta;
  }, [mode, body, storedAnchor]);

  // jump to the active search hit
  useEffect(() => {
    const id = searchHits[searchIndex];
    if (!id) return;
    document.getElementById(`block-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [searchHits, searchIndex]);

  return (
    <div id="reading-scroll" className="h-full overflow-y-auto px-4 py-6">
      <div
        className="reading-body mx-auto max-w-[74ch]"
        style={{ fontSize: `${1.0625 * fontScale}rem` }}
        onClick={() => setActiveBlock(null)}
      >
        {visible.length === 0 && (
          <div className="mt-16 text-center text-sm text-ink-2">{t("正在解析或没有可显示的正文…")}</div>
        )}

        {leadingMeta.length > 0 && (
          <section className="mb-6 rounded-xl border border-line bg-paper-2/70 p-3">
            <div className="mb-2 flex items-center gap-2 text-[11px] text-ink-3">
              <span className="chip">{t("文章信息")}</span>
              <span>{t("以下内容来自出版商的元信息栏，不属于正文，因此单独列出")}</span>
            </div>
            <div className="space-y-1.5" style={{ fontFamily: "var(--font-sans)", fontSize: "0.83rem" }}>
              {leadingMeta.map((block) => (
                <div key={block.id} className="flex gap-2">
                  <span className="mt-[3px] h-1.5 w-1.5 shrink-0 rounded-full bg-accent-strong" />
                  <span className="text-ink-2">{block.text}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {body.map((block) => (
          <BlockView
            key={block.id}
            block={block}
            mode={mode}
            lang={lang}
            search={search}
            active={activeBlockId === block.id}
            onActivate={() => {
              setActiveBlock(block.id);
              setScrolledBlock(block.id);
            }}
            onRetranslate={() => void translateBlock(block.id)}
          />
        ))}
        {visible.length > 0 && (
          <p className="mt-12 text-center text-xs text-ink-3">
            {t("解析结果与原页面可能存在细微差异 —— 如需核对，可切换到「原版页」模式查看原始排版。")}
          </p>
        )}
      </div>
    </div>
  );
}
