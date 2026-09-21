/**
 * Pure translation layer (no React, no store import) so the store can use it
 * without creating an import cycle.
 *
 * The Chinese source string is the key: the app was written with Chinese
 * literals inline, so keying on the literal keeps the diff mechanical and a
 * missing translation degrades to the Chinese text instead of a raw key.
 */
import { CORE_DICT } from "./dict.core";
import { CHANNEL_DICT } from "./dict.channels";
import { SETTINGS_DICT } from "./dict.settings";
import { VIEWS_DICT } from "./dict.views";

export type UiLang = "zh" | "en";

export const UI_LANG_KEY = "essay-reader:ui-lang";

const DICT: Record<string, string> = {
  ...CORE_DICT,
  ...CHANNEL_DICT,
  ...SETTINGS_DICT,
  ...VIEWS_DICT,
};

/** Follow the system language: Chinese browsers get Chinese, everyone else English. */
export function detectUiLang(): UiLang {
  try {
    const stored = localStorage.getItem(UI_LANG_KEY);
    if (stored === "zh" || stored === "en") return stored;
    const candidates = [navigator.language, ...(navigator.languages || [])];
    for (const value of candidates) {
      if (!value) continue;
      if (/^zh\b/i.test(value)) return "zh";
      if (/^[a-z]{2}\b/i.test(value)) return "en";
    }
  } catch {
    /* non-browser context */
  }
  return "en";
}

export function translate(lang: UiLang, text: string, vars?: Record<string, string | number>): string {
  let out = lang === "en" ? (DICT[text] ?? text) : text;
  if (vars) {
    for (const [key, value] of Object.entries(vars)) {
      out = out.split(`{${key}}`).join(String(value));
    }
  }
  return out;
}

let langGetter: () => UiLang = () => "zh";

/** Wired by the store so non-React code (store actions, api client) sees the setting. */
export function bindLangGetter(getter: () => UiLang): void {
  langGetter = getter;
}

export function currentUiLang(): UiLang {
  return langGetter();
}

/** For non-React call sites. */
export function t(text: string, vars?: Record<string, string | number>): string {
  return translate(currentUiLang(), text, vars);
}
