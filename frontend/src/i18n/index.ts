/** React bindings for the translation layer. */
import { useMemo } from "react";

import { useApp } from "../store";

import { translate, type UiLang } from "./translate";

export * from "./translate";

/** `const t = useT()` — re-renders when the UI language changes. */
export function useT() {
  const lang = useApp((state) => state.uiLang);
  return useMemo(
    () => (text: string, vars?: Record<string, string | number>) => translate(lang, text, vars),
    [lang],
  );
}

export function useUiLang(): UiLang {
  return useApp((state) => state.uiLang);
}
