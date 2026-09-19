import { useEffect } from "react";

import { useApp } from "../store";

export function Lightbox() {
  const lightbox = useApp((s) => s.lightbox);
  const close = useApp((s) => s.closeLightbox);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  if (!lightbox) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-ink/70 p-4 backdrop-blur-sm"
      onClick={close}
    >
      <img
        src={lightbox.src}
        alt={lightbox.caption || "figure"}
        className="max-h-[82vh] max-w-[94vw] rounded-xl border border-line bg-surface object-contain shadow-lg"
        onClick={(event) => event.stopPropagation()}
      />
      <div className="max-w-[80ch] text-center text-xs leading-relaxed text-paper">
        {lightbox.caption || "原图裁切（解析器按 bbox 保留，可与正文对照）"}
      </div>
      <button className="btn" onClick={close}>
        关闭 (Esc)
      </button>
    </div>
  );
}
