import { useRef, useState } from "react";

import { useT } from "../i18n";
import { useApp } from "../store";

export function UploadDropzone({ compact = false }: { compact?: boolean }) {
  const t = useT();
  const upload = useApp((s) => s.upload);
  const uploading = useApp((s) => s.uploading);
  const ocrMode = useApp((s) => s.ocrMode);
  const setOcrMode = useApp((s) => s.setOcrMode);
  const ocrReady = useApp((s) => Boolean(s.environment?.ocr?.available));
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const pick = () => inputRef.current?.click();

  const ocrToggle = (
    <label
      className="flex items-center gap-1.5 text-[11px] text-ink-3"
      title={t("扫描件（没有文本层）需要 OCR；文本层 PDF 会自动跳过 OCR")}
      onClick={(event) => event.stopPropagation()}
    >
      <input
        type="checkbox"
        disabled={!ocrReady}
        checked={ocrMode !== "off"}
        onChange={(event) => setOcrMode(event.target.checked ? "auto" : "off")}
      />
      {t("扫描件 OCR{state}", { state: ocrReady ? t("（本地离线）") : t("（引擎不可用）") })}
    </label>
  );

  return (
    <div
      className={`rounded-xl border border-dashed transition ${
        dragging ? "border-accent-strong bg-accent-soft" : "border-line-2 bg-surface/70 hover:bg-accent-soft/50"
      } ${compact ? "p-2.5" : "p-8"}`}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        const file = Array.from(event.dataTransfer.files).find((f) => f.name.toLowerCase().endsWith(".pdf"));
        if (file) void upload(file);
        else useApp.getState().toast("warn", t("只支持 PDF 文件"));
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void upload(file);
          event.target.value = "";
        }}
      />

      {uploading ? (
        <div className="text-xs text-ink-2">
          <div className="mb-1 truncate">{uploading.name}</div>
          <div className="h-1.5 overflow-hidden rounded-full bg-paper-3">
            <div className="h-full bg-accent-strong" style={{ width: `${uploading.percent}%` }} />
          </div>
          <div className="mt-1 text-[11px] text-ink-3">
            {uploading.percent < 100
              ? t("上传中 {percent}%", { percent: uploading.percent })
              : t("解析中（扫描件 OCR 约 1~3 秒/页）…")}
          </div>
        </div>
      ) : compact ? (
        <div className="space-y-2">
          <button className="btn w-full justify-center" onClick={pick}>
            {t("＋ 上传 PDF")}
          </button>
          {ocrToggle}
        </div>
      ) : (
        <div className="space-y-3">
          <button className="w-full text-center" onClick={pick}>
            <div className="text-3xl">📄</div>
            <div className="mt-3 text-sm font-medium">{t("拖入 PDF，或点击选择文件")}</div>
            <div className="mt-1 text-xs text-ink-3">
              {t("本地解析：双栏、图表、公式都会保留；不会上传到任何服务器")}
            </div>
          </button>
          <div className="flex justify-center">{ocrToggle}</div>
        </div>
      )}
    </div>
  );
}
