import { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

import { api } from "../api/client";
import { useT } from "../i18n";
import { useApp } from "../store";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const TARGET_WIDTH = 720;

export function PdfPane() {
  const t = useT();
  const doc = useApp((s) => s.doc);
  const blocks = useApp((s) => s.blocks);
  const activeBlockId = useApp((s) => s.activeBlockId);
  const setActiveBlock = useApp((s) => s.setActiveBlock);

  const [pdf, setPdf] = useState<pdfjs.PDFDocumentProxy | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!doc) return;
    let cancelled = false;
    setPdf(null);
    setError("");
    pdfjs
      .getDocument({ url: api.pdfUrl(doc.id) })
      .promise.then((loaded) => {
        if (!cancelled) setPdf(loaded);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(t("PDF 渲染失败：{reason}", { reason: String(reason) }));
      });
    return () => {
      cancelled = true;
    };
  }, [doc]);

  if (error) {
    return <div className="flex h-full items-center justify-center text-sm text-danger">{error}</div>;
  }
  if (!pdf) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-ink-2">
        <span className="skeleton inline-block h-2 w-2 rounded-full" /> {t("正在加载原始 PDF…")}
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-paper-3/50 px-4 py-6">
      <p className="mx-auto mb-3 max-w-[820px] text-center text-[11px] text-ink-3">
        {t("原版页模式：按真实排版渲染，选中段落会在页面上高亮对应区域 —— 这是核对解析与图表位置的最可靠方式。")}
      </p>
      <div className="mx-auto flex max-w-[820px] flex-col gap-6">
        {Array.from({ length: pdf.numPages }, (_, index) => (
          <PdfPage
            key={index}
            pdf={pdf}
            pageIndex={index}
            pageBlocks={blocks.filter((block) => block.page === index)}
            activeBlockId={activeBlockId}
            onPick={setActiveBlock}
          />
        ))}
      </div>
    </div>
  );
}

function PdfPage({
  pdf,
  pageIndex,
  pageBlocks,
  activeBlockId,
  onPick,
}: {
  pdf: pdfjs.PDFDocumentProxy;
  pageIndex: number;
  pageBlocks: {
    id: string;
    type: string;
    bbox: { x0: number; y0: number; x1: number; y1: number };
  }[];
  activeBlockId: string | null;
  onPick: (blockId: string) => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  const [scale, setScale] = useState(1);
  const [rendered, setRendered] = useState(false);

  // render only when the page scrolls near the viewport
  useEffect(() => {
    const node = wrapRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setRendered(true);
          observer.disconnect();
        }
      },
      { rootMargin: "600px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!rendered) return;
    let cancelled = false;
    void (async () => {
      const page = await pdf.getPage(pageIndex + 1);
      if (cancelled) return;
      const base = page.getViewport({ scale: 1 });
      const targetScale = TARGET_WIDTH / base.width;
      const viewport = page.getViewport({ scale: targetScale });
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");
      if (!canvas || !context) return;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      setSize({ width: viewport.width, height: viewport.height });
      setScale(targetScale);
      await page.render({
        canvas,
        canvasContext: context,
        viewport,
        transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
      } as never).promise;
    })();
    return () => {
      cancelled = true;
    };
  }, [pdf, pageIndex, rendered]);

  return (
    <div
      id={`pdfpage-${pageIndex}`}
      ref={wrapRef}
      className="relative mx-auto w-full rounded-xl border border-line bg-surface"
      style={size ? { width: size.width, height: size.height } : { minHeight: 400 }}
    >
      {!rendered && <div className="skeleton absolute inset-0 rounded-xl" />}
      <canvas ref={canvasRef} className="block rounded-xl" />
      {size &&
        pageBlocks
          .filter((block) => block.id === activeBlockId)
          .map((block) => (
            <div
              key={block.id}
              className="pdf-page-highlight"
              style={{
                left: block.bbox.x0 * scale,
                top: block.bbox.y0 * scale,
                width: Math.max(3, (block.bbox.x1 - block.bbox.x0) * scale),
                height: Math.max(3, (block.bbox.y1 - block.bbox.y0) * scale),
              }}
              onClick={() => onPick(block.id)}
            />
          ))}
    </div>
  );
}
