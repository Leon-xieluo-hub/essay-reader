import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * A dropdown that escapes every parent stacking context.
 *
 * The top bar uses `backdrop-blur`, which creates its own stacking context, so
 * a normally-positioned dropdown is painted *under* the reading pane no matter
 * how high its z-index is. Rendering into a document.body portal and
 * positioning with fixed coordinates sidesteps that entirely.
 */
export function FloatingPanel({
  anchor,
  open,
  onClose,
  align = "left",
  width = 320,
  children,
}: {
  anchor: HTMLElement | null;
  open: boolean;
  onClose: () => void;
  align?: "left" | "right";
  width?: number;
  children: React.ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  useEffect(() => {
    if (!open || !anchor) return;
    const update = () => {
      const rect = anchor.getBoundingClientRect();
      const margin = 8;
      const maxWidth = Math.min(width, window.innerWidth - margin * 2);
      let left = align === "right" ? rect.right - maxWidth : rect.left;
      left = Math.max(margin, Math.min(left, window.innerWidth - maxWidth - margin));
      const top = Math.min(rect.bottom + 6, window.innerHeight - 80);
      setPosition({ top, left });
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open, anchor, align, width]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (panelRef.current?.contains(target) || anchor?.contains(target)) return;
      onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, anchor, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      ref={panelRef}
      className="card fade-in fixed p-3 text-sm"
      style={{
        top: position?.top ?? -9999,
        left: position?.left ?? -9999,
        width: Math.min(width, window.innerWidth - 16),
        zIndex: 200,
      }}
      role="dialog"
    >
      {children}
    </div>,
    document.body,
  );
}
