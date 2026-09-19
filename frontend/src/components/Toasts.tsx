import { useApp } from "../store";

const STYLES: Record<string, string> = {
  info: "border-line bg-surface",
  ok: "border-ok bg-surface",
  warn: "border-warn bg-surface",
  error: "border-danger bg-surface",
};

const ICONS: Record<string, string> = { info: "ℹ", ok: "✓", warn: "!", error: "✕" };

export function Toasts() {
  const toasts = useApp((s) => s.toasts);
  const dismiss = useApp((s) => s.dismissToast);
  if (!toasts.length) return null;
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(92vw,26rem)] flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`card fade-in pointer-events-auto flex items-start gap-2 border-l-4 px-3 py-2 text-sm ${
            STYLES[toast.kind]
          }`}
        >
          <span className="mt-0.5 text-xs text-ink-2">{ICONS[toast.kind]}</span>
          <span className="flex-1 leading-relaxed">{toast.text}</span>
          <button className="btn btn-ghost !px-1 !py-0" onClick={() => dismiss(toast.id)}>
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
