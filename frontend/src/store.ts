import { create } from "zustand";

import { api } from "./api/client";
import { UI_LANG_KEY, bindLangGetter, detectUiLang, t, type UiLang } from "./i18n/translate";
import type {
  AskAnswer,
  DocBlock,
  DocumentDetail,
  DocumentMeta,
  EnvironmentInfo,
  GlossaryTerm,
  Note,
  OcrMode,
  ProviderKey,
  ProviderStatus,
  SettingsDict,
  TaskState,
  TranslateEstimate,
  UsageStats,
} from "./api/types";

export type ReadingMode = "bilingual" | "translated" | "original" | "pdf";
export type ThemeChoice = "system" | "light" | "dark";
export type DockTab = "summary" | "chat" | "notes" | "glossary" | "quality";

interface Toast {
  id: number;
  kind: "info" | "ok" | "warn" | "error";
  text: string;
}

interface AppState {
  // environment
  environment: EnvironmentInfo | null;
  providers: ProviderStatus[];
  settings: SettingsDict | null;
  usage: UsageStats | null;

  // documents
  documents: DocumentMeta[];
  doc: DocumentDetail | null;
  blocks: DocBlock[];
  loadingDoc: boolean;
  uploading: { name: string; percent: number } | null;

  // reading
  mode: ReadingMode;
  lang: string;
  uiLang: UiLang;
  provider: ProviderKey;
  ocrMode: OcrMode;
  theme: ThemeChoice;
  fontScale: number;
  activeBlockId: string | null;
  scrolledBlockId: string | null;
  /** anchor for the text reading views — lives here so it survives switching to
   *  the original-page view, which unmounts the reading pane */
  scrollAnchorId: string | null;
  /** the original-page view keeps its own position; it is never synced with the
   *  text views (a rendered page image has no paragraph anchors to align to) */
  pdfPage: number;
  search: string;
  searchHits: string[];
  searchIndex: number;

  // panels
  sidebarOpen: boolean;
  dockOpen: boolean;
  dockTab: DockTab;
  lightbox: { src: string; caption: string } | null;

  // content
  notes: Note[];
  glossary: GlossaryTerm[];
  summary: string;
  chat: { role: "user" | "assistant"; text: string; evidence?: AskAnswer["evidence"]; grounded?: boolean }[];
  estimate: TranslateEstimate | null;

  // tasks
  task: TaskState | null;

  toasts: Toast[];

  // actions
  bootstrap: () => Promise<void>;
  refreshDocuments: () => Promise<void>;
  openDocument: (docId: string) => Promise<void>;
  closeDocument: () => void;
  upload: (file: File) => Promise<void>;
  removeDocument: (docId: string) => Promise<void>;

  setMode: (mode: ReadingMode) => void;
  setLang: (lang: string) => void;
  setUiLang: (lang: UiLang) => void;
  setOcrMode: (mode: OcrMode) => void;
  setTheme: (theme: ThemeChoice) => void;
  setProvider: (provider: ProviderKey) => Promise<void>;
  setFontScale: (scale: number) => void;
  setActiveBlock: (blockId: string | null) => void;
  setScrolledBlock: (blockId: string | null) => void;
  setScrollAnchor: (blockId: string | null) => void;
  setPdfPage: (page: number) => void;
  setSearch: (value: string) => void;
  cycleSearchHit: (delta: number) => void;

  toggleSidebar: () => void;
  toggleDock: (tab?: DockTab) => void;
  setDockTab: (tab: DockTab) => void;
  openLightbox: (src: string, caption: string) => void;
  closeLightbox: () => void;

  loadBlocks: (lang?: string) => Promise<void>;
  runEstimate: (blockIds?: string[]) => Promise<void>;
  translate: (options?: { blockIds?: string[]; force?: boolean }) => Promise<void>;
  translateBlock: (blockId: string) => Promise<void>;
  runSummary: (force?: boolean) => Promise<void>;
  ask: (question: string, blockIds?: string[]) => Promise<void>;
  clearChat: () => void;
  loadNotes: () => Promise<void>;
  addNote: (blockId: string, quote: string, comment: string) => Promise<void>;
  removeNote: (noteId: number) => Promise<void>;
  loadGlossary: () => Promise<void>;
  saveTerm: (source: string, target: string, note?: string) => Promise<void>;
  removeTerm: (termId: number) => Promise<void>;
  buildGlossary: () => Promise<void>;
  saveSettings: (payload: Record<string, unknown>) => Promise<void>;
  refreshUsage: () => Promise<void>;
  resetUsage: () => Promise<void>;

  toast: (kind: Toast["kind"], text: string) => void;
  dismissToast: (id: number) => void;
}

const THEME_KEY = "essay-reader:theme";
const LANG_KEY = "essay-reader:lang";
const MODE_KEY = "essay-reader:mode";
const PROVIDER_KEY = "essay-reader:provider";
const OCR_KEY = "essay-reader:ocr";

function applyTheme(theme: ThemeChoice) {
  const resolved =
    theme === "system"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : theme;
  document.documentElement.dataset.theme = resolved;
}

let toastSeq = 0;
let pollTimer: number | null = null;

export const useApp = create<AppState>((set, get) => ({
  environment: null,
  providers: [],
  settings: null,
  usage: null,

  documents: [],
  doc: null,
  blocks: [],
  loadingDoc: false,
  uploading: null,

  mode: (localStorage.getItem(MODE_KEY) as ReadingMode) || "bilingual",
  lang: localStorage.getItem(LANG_KEY) || "zh",
  uiLang: detectUiLang(),
  provider: (localStorage.getItem(PROVIDER_KEY) as ProviderKey) || "off",
  ocrMode: (localStorage.getItem(OCR_KEY) as OcrMode) || "auto",
  theme: (localStorage.getItem(THEME_KEY) as ThemeChoice) || "system",
  fontScale: Number(localStorage.getItem("essay-reader:scale") || "1"),
  activeBlockId: null,
  scrolledBlockId: null,
  scrollAnchorId: null,
  pdfPage: 0,
  search: "",
  searchHits: [],
  searchIndex: 0,

  sidebarOpen: true,
  dockOpen: false,
  dockTab: "summary",
  lightbox: null,

  notes: [],
  glossary: [],
  summary: "",
  chat: [],
  estimate: null,
  task: null,
  toasts: [],

  async bootstrap() {
    applyTheme(get().theme);
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", () => applyTheme(get().theme));
    await Promise.all([get().refreshDocuments(), get().refreshUsage()]);
    try {
      const [environment, providers, settings] = await Promise.all([
        api.environment(),
        api.providers(),
        api.settings(),
      ]);
      set({ environment, providers, settings });
      if (environment.configured.llm_provider) {
        const stored = localStorage.getItem(PROVIDER_KEY) as ProviderKey | null;
        set({ provider: stored || environment.configured.llm_provider });
      }
      if (environment.ocr?.mode) {
        // the backend is the source of truth for the OCR default
        set({ ocrMode: environment.ocr.mode });
      }
    } catch (error) {
      get().toast("error", t("无法连接本地服务：{msg}", { msg: (error as Error).message }));
    }
  },

  async refreshDocuments() {
    try {
      set({ documents: await api.listDocuments() });
    } catch (error) {
      get().toast("error", (error as Error).message);
    }
  },

  async openDocument(docId) {
    // Positions belong to a document: start a newly opened paper at the top of
    // both the text views and the original-page view.
    set({
      loadingDoc: true,
      search: "",
      searchHits: [],
      chat: [],
      scrollAnchorId: null,
      scrolledBlockId: null,
      activeBlockId: null,
      pdfPage: 0,
    });
    try {
      const doc = await api.getDocument(docId);
      set({ doc, loadingDoc: false });
      document.title = `${doc.title || doc.filename} · Essay Reader`;
      await Promise.all([
        get().loadBlocks(),
        get().loadNotes(),
        get().loadGlossary(),
        api.summary(docId, get().lang).then((res) => set({ summary: res.content })),
      ]);
    } catch (error) {
      set({ loadingDoc: false, doc: null });
      get().toast("error", (error as Error).message);
    }
  },

  closeDocument() {
    set({ doc: null, blocks: [], summary: "", notes: [], glossary: [], chat: [], task: null });
    document.title = t("Essay Reader · 文献阅读器");
  },

  async upload(file) {
    set({ uploading: { name: file.name, percent: 0 } });
    const ocrMode = get().ocrMode;
    try {
      const doc = await api.uploadDocument(file, ocrMode, (percent) =>
        set({ uploading: { name: file.name, percent } }),
      );
      const report = doc.parse_report;
      const quality = report ? Math.round(qualityScore(report)) : 100;
      const channel = report?.ocr_pages
        ? t(" · OCR {pages} 页（置信度 {conf}%）", {
              pages: report.ocr_pages,
              conf: (report.ocr_confidence * 100).toFixed(0),
            })
        : "";
      get().toast(
        "ok",
        t("解析完成：{pages} 页 · 质量 {quality} 分{channel} · {ms}ms", {
          pages: doc.page_count,
          quality,
          channel,
          ms: report?.duration_ms ?? 0,
        }),
      );
      if (report?.warnings?.length) {
        for (const warning of report.warnings.slice(0, 2)) get().toast("warn", warning);
      }
      set({ uploading: null });
      await get().refreshDocuments();
      window.location.hash = `#/doc/${doc.id}`;
    } catch (error) {
      set({ uploading: null });
      get().toast("error", (error as Error).message);
    }
  },

  async removeDocument(docId) {
    try {
      await api.deleteDocument(docId);
      if (get().doc?.id === docId) {
        window.location.hash = "#/";
        get().closeDocument();
      }
      await get().refreshDocuments();
      get().toast("ok", t("已删除文献及本地缓存"));
    } catch (error) {
      get().toast("error", (error as Error).message);
    }
  },

  setMode(mode) {
    localStorage.setItem(MODE_KEY, mode);
    set({ mode });
  },
  setOcrMode(mode) {
    localStorage.setItem(OCR_KEY, mode);
    set({ ocrMode: mode });
    void api.saveSettings({ ocr_mode: mode }).then(() => api.environment().then((env) => set({ environment: env })));
  },

  setLang(lang) {
    localStorage.setItem(LANG_KEY, lang);
    set({ lang });
    if (get().doc) {
      void get().loadBlocks(lang);
      void api.summary(get().doc!.id, lang).then((res) => set({ summary: res.content }));
    }
  },

  setUiLang(uiLang) {
    localStorage.setItem(UI_LANG_KEY, uiLang);
    set({ uiLang });
  },

  setTheme(theme) {    localStorage.setItem(THEME_KEY, theme);
    applyTheme(theme);
    set({ theme });
  },

  async setProvider(provider) {
    localStorage.setItem(PROVIDER_KEY, provider);
    set({ provider });
    try {
      await api.saveSettings({ llm_provider: provider });
      set({ providers: await api.providers() });
    } catch (error) {
      get().toast("error", (error as Error).message);
    }
  },

  setFontScale(scale) {
    const clamped = Math.min(1.5, Math.max(0.85, Number(scale.toFixed(2))));
    localStorage.setItem("essay-reader:scale", String(clamped));
    set({ fontScale: clamped });
  },

  setActiveBlock(blockId) {
    set({ activeBlockId: blockId });
  },

  setScrolledBlock(blockId) {
    set({ scrolledBlockId: blockId });
  },

  setScrollAnchor(blockId) {
    set({ scrollAnchorId: blockId });
  },

  setPdfPage(page) {
    set({ pdfPage: page });
  },

  setSearch(value) {
    const needle = value.trim().toLowerCase();
    if (!needle) {
      set({ search: value, searchHits: [], searchIndex: 0 });
      return;
    }
    const hits = get()
      .blocks.filter(
        (block) =>
          block.type !== "meta" &&
          (block.text.toLowerCase().includes(needle) ||
            Object.values(block.translations).some((t) => t.toLowerCase().includes(needle))),
      )
      .map((block) => block.id);
    set({ search: value, searchHits: hits, searchIndex: 0 });
  },

  cycleSearchHit(delta) {
    const { searchHits, searchIndex } = get();
    if (!searchHits.length) return;
    const next = (searchIndex + delta + searchHits.length) % searchHits.length;
    set({ searchIndex: next, activeBlockId: searchHits[next] });
  },

  toggleSidebar() {
    set({ sidebarOpen: !get().sidebarOpen });
  },

  toggleDock(tab) {
    const { dockOpen, dockTab } = get();
    if (tab && (!dockOpen || dockTab !== tab)) {
      set({ dockOpen: true, dockTab: tab });
      return;
    }
    set({ dockOpen: !dockOpen });
  },

  setDockTab(tab) {
    set({ dockTab: tab, dockOpen: true });
  },

  openLightbox(src, caption) {
    set({ lightbox: { src, caption } });
  },

  closeLightbox() {
    set({ lightbox: null });
  },

  async loadBlocks(lang) {
    const doc = get().doc;
    if (!doc) return;
    try {
      set({ blocks: await api.getBlocks(doc.id, lang ?? get().lang) });
    } catch (error) {
      get().toast("error", (error as Error).message);
    }
  },

  async runEstimate(blockIds) {
    const doc = get().doc;
    if (!doc) return;
    try {
      set({
        estimate: await api.estimate({
          doc_id: doc.id,
          provider: get().provider,
          lang: get().lang,
          style: "academic",
          ...(blockIds ? { block_ids: blockIds } : {}),
        } as never),
      });
    } catch {
      set({ estimate: null });
    }
  },

  async translate(options) {
    const doc = get().doc;
    if (!doc) return;
    const provider = get().provider;
    if (provider === "off") {
      get().toast("warn", t("AI 功能已关闭：请先在设置中启用本地模型或配置云端 API"));
      return;
    }
    const label = provider === "local" ? t("本地模型") : t("云端模型");
    try {
      const task = await api.translate({
        doc_id: doc.id,
        provider,
        lang: get().lang,
        style: "academic",
        block_ids: options?.blockIds,
        force: options?.force,
      });
      set({ task });
      get().toast("info", t("{label}开始翻译…", { label }));
      startPolling(get, set, task, async () => {
        await get().loadBlocks();
        await get().refreshUsage();
      });
    } catch (error) {
      get().toast("error", (error as Error).message);
    }
  },

  async translateBlock(blockId) {
    await get().translate({ blockIds: [blockId], force: true });
  },

  async runSummary(force) {
    const doc = get().doc;
    if (!doc) return;
    const provider = get().provider;
    if (provider === "off") {
      get().toast("warn", t("AI 功能已关闭：请先启用模型通道"));
      return;
    }
    try {
      const task = await api.createSummary({ doc_id: doc.id, provider, lang: get().lang, force });
      set({ task });
      startPolling(get, set, task, async () => {
        const res = await api.summary(doc.id, get().lang);
        set({ summary: res.content });
        await get().refreshUsage();
      });
    } catch (error) {
      get().toast("error", (error as Error).message);
    }
  },

  async ask(question, blockIds) {
    const doc = get().doc;
    if (!doc) return;
    const provider = get().provider;
    if (provider === "off") {
      get().toast("warn", "AI 功能已关闭：请先启用模型通道");
      return;
    }
    set({ chat: [...get().chat, { role: "user", text: question }] });
    try {
      const res = await api.ask({
        doc_id: doc.id,
        question,
        provider,
        lang: get().lang,
        block_ids: blockIds,
      });
      set({
        chat: [
          ...get().chat,
          { role: "assistant", text: res.answer, evidence: res.evidence, grounded: res.grounded },
        ],
      });
      await get().refreshUsage();
    } catch (error) {
      set({
        chat: [
          ...get().chat,
          { role: "assistant", text: t("出错：{msg}", { msg: (error as Error).message }) },
        ],
      });
    }
  },

  clearChat() {
    set({ chat: [] });
  },

  async loadNotes() {
    const doc = get().doc;
    if (!doc) return;
    set({ notes: await api.notes(doc.id) });
  },

  async addNote(blockId, quote, comment) {
    const doc = get().doc;
    if (!doc) return;
    try {
      await api.addNote({ doc_id: doc.id, block_id: blockId, quote, comment });
      await Promise.all([get().loadNotes(), get().loadBlocks()]);
      get().toast("ok", t("已保存笔记"));
    } catch (error) {
      get().toast("error", (error as Error).message);
    }
  },

  async removeNote(noteId) {
    await api.deleteNote(noteId);
    await Promise.all([get().loadNotes(), get().loadBlocks()]);
  },

  async loadGlossary() {
    const doc = get().doc;
    if (!doc) return;
    set({ glossary: await api.glossary(doc.id) });
  },

  async saveTerm(source, target, note) {
    const doc = get().doc;
    if (!doc) return;
    try {
      set({ glossary: await api.saveTerm(doc.id, { source, target, note }) });
      get().toast("ok", t("术语已更新，将应用于后续翻译"));
    } catch (error) {
      get().toast("error", (error as Error).message);
    }
  },

  async removeTerm(termId) {
    const doc = get().doc;
    if (!doc) return;
    await api.deleteTerm(doc.id, termId);
    set({ glossary: await api.glossary(doc.id) });
  },

  async buildGlossary() {
    const doc = get().doc;
    if (!doc) return;
    try {
      const res = await api.buildGlossary(doc.id, get().provider, get().lang);
      set({ glossary: res.terms });
      get().toast("ok", t("已抽取 {count} 条术语", { count: res.terms.length }));
    } catch (error) {
      get().toast("error", (error as Error).message);
    }
  },

  async saveSettings(payload) {
    try {
      const res = await api.saveSettings(payload as never);
      set({ settings: res.settings });
      set({ providers: await api.providers() });
      const environment = await api.environment();
      set({ environment });
      get().toast(
          "ok",
          res.changed.length
            ? t("已更新：{fields}", { fields: res.changed.join(", ") })
            : t("设置未变化"),
        );
    } catch (error) {
      get().toast("error", (error as Error).message);
    }
  },

  async refreshUsage() {
    try {
      set({ usage: await api.usage() });
    } catch {
      /* usage is informational */
    }
  },

  async resetUsage() {
    await api.resetUsage();
    await get().refreshUsage();
  },

  toast(kind, text) {
    const id = ++toastSeq;
    set({ toasts: [...get().toasts, { id, kind, text }] });
    window.setTimeout(() => get().dismissToast(id), kind === "error" ? 6500 : 3600);
  },

  dismissToast(id) {
    set({ toasts: get().toasts.filter((t) => t.id !== id) });
  },
}));

export function qualityScore(report: {
  paragraph_count: number;
  garbage_ratio: number;
  text_coverage: number;
  warnings: string[];
  ocr_pages?: number;
  ocr_confidence?: number;
}) {
  let score = 100;
  score -= Math.min(40, report.garbage_ratio * 400);
  if (!report.paragraph_count) score -= 30;
  if (report.text_coverage <= 0.02) score -= 25;
  // OCR text is a best-effort reconstruction and must never look as reliable
  // as a clean text layer.
  if (report.ocr_pages) {
    score -= Math.min(20, 4 + 0.06 * report.ocr_pages);
    const confidence = report.ocr_confidence ?? 0;
    if (confidence && confidence < 0.85) score -= Math.min(15, (0.85 - confidence) * 60);
  }
  score -= 5 * report.warnings.length;
  return Math.max(0, Math.min(100, score));
}

function startPolling(
  get: () => AppState,
  set: (partial: Partial<AppState>) => void,
  task: TaskState,
  onDone: () => Promise<void>,
) {
  if (pollTimer) window.clearInterval(pollTimer);
  pollTimer = window.setInterval(async () => {
    try {
      const latest = await api.task(task.id);
      set({ task: latest });
      if (latest.status !== "running") {
        if (pollTimer) window.clearInterval(pollTimer);
        pollTimer = null;
        await onDone();
        if (latest.status === "done") {
          get().toast("ok", describeTaskDone(latest));
        } else {
          get().toast("error", latest.error || t("任务失败"));
        }
      }
    } catch {
      if (pollTimer) window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }, 900);
}

function describeTaskDone(task: TaskState): string {
  try {
    const payload = JSON.parse(task.message || "{}");
    if (task.kind === "translate") {
      const parts = [t("已翻译 {count} 段", { count: payload.translated ?? 0 })];
      if (payload.skipped) parts.push(t("复用缓存 {count} 段", { count: payload.skipped }));
      if (payload.suspect) parts.push(t("待复核 {count} 段", { count: payload.suspect }));
      if (payload.failed) parts.push(t("失败 {count} 段", { count: payload.failed }));
      return parts.join(" · ");
    }
    if (task.kind === "summary") return t("要点总结已生成");
  } catch {
    /* fall through */
  }
  return t("任务完成");
}

// Non-React call sites (task messages, api errors) need the live UI language.
bindLangGetter(() => useApp.getState().uiLang);
