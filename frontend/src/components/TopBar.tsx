import { useState } from "react";

import { api } from "../api/client";
import type { ProviderKey } from "../api/types";
import { navigate } from "../hooks/useHashRoute";
import { useT } from "../i18n";
import { useApp, type ReadingMode } from "../store";

import { FloatingPanel } from "./FloatingPanel";
import { SetupGuidePanel } from "./SetupGuidePanel";

const MODES: { key: ReadingMode; label: string; hint: string }[] = [
  { key: "bilingual", label: "双语", hint: "原文与译文逐段对照" },
  { key: "translated", label: "译文", hint: "只看译文" },
  { key: "original", label: "原文", hint: "只看提取的原文" },
  { key: "pdf", label: "原版页", hint: "渲染原始 PDF 页面，逐块高亮" },
];

const LANGS = [
  { key: "zh", label: "简体中文" },
  { key: "zh-tw", label: "繁體中文" },
  { key: "en", label: "English" },
  { key: "ja", label: "日本語" },
];

export function TopBar() {
  const doc = useApp((s) => s.doc);
  const mode = useApp((s) => s.mode);
  const setMode = useApp((s) => s.setMode);
  const lang = useApp((s) => s.lang);
  const setLang = useApp((s) => s.setLang);
  const provider = useApp((s) => s.provider);
  const setProvider = useApp((s) => s.setProvider);
  const providers = useApp((s) => s.providers);
  const task = useApp((s) => s.task);
  const translate = useApp((s) => s.translate);
  const runEstimate = useApp((s) => s.runEstimate);
  const setDockTab = useApp((s) => s.setDockTab);
  const toggleDock = useApp((s) => s.toggleDock);
  const dockOpen = useApp((s) => s.dockOpen);
  const dockTab = useApp((s) => s.dockTab);
  const theme = useApp((s) => s.theme);
  const setTheme = useApp((s) => s.setTheme);
  const uiLang = useApp((s) => s.uiLang);
  const setUiLang = useApp((s) => s.setUiLang);
  const search = useApp((s) => s.search);
  const setSearch = useApp((s) => s.setSearch);
  const searchHits = useApp((s) => s.searchHits);
  const searchIndex = useApp((s) => s.searchIndex);
  const cycleSearchHit = useApp((s) => s.cycleSearchHit);
  const toggleSidebar = useApp((s) => s.toggleSidebar);
  const estimate = useApp((s) => s.estimate);
  const usage = useApp((s) => s.usage);
  const t = useT();

  const [menu, setMenu] = useState<"" | "export" | "channel">("");
  const [channelAnchor, setChannelAnchor] = useState<HTMLElement | null>(null);
  const [exportAnchor, setExportAnchor] = useState<HTMLElement | null>(null);
  const [guideFor, setGuideFor] = useState<ProviderKey | null>(null);

  const localStatus = providers.find((p) => p.name === "local");
  const cloudStatus = providers.find((p) => p.name === "cloud");
  const activeStatus = provider === "local" ? localStatus : provider === "cloud" ? cloudStatus : null;
  const channelReady = provider !== "off" && Boolean(activeStatus?.available);
  const busy = task?.status === "running";

  const channelLabel =
    provider === "off"
      ? t("AI 已关闭")
      : provider === "local"
        ? t("本地 · {model}", { model: activeStatus?.model || t("未配置") })
        : t("云端 · {model}", { model: activeStatus?.model || t("未配置") });

  const chooseChannel = async (key: ProviderKey) => {
    setMenu("");
    await setProvider(key);
    if (key !== "off") {
      const ready = key === "local" ? localStatus?.available : cloudStatus?.available;
      if (!ready) setGuideFor(key);            // guide instead of a dead end
    }
  };

  return (
    <header className="relative z-30 flex flex-wrap items-center gap-2 border-b border-line bg-paper-2/90 px-3 py-2 backdrop-blur">
      <button className="btn btn-ghost" onClick={toggleSidebar} title={t("折叠/展开侧栏")}>
        ☰
      </button>
      <div className="min-w-0">
        <button className="btn btn-ghost max-w-[38ch] truncate" onClick={() => navigate("#/")}>
          <span className="truncate font-medium">{doc ? doc.title || doc.filename : "Essay Reader"}</span>
        </button>
      </div>

      {doc && (
        <>
          <span className="hidden text-xs text-ink-3 sm:inline">
            {t("{pages} 页 · {authors}", { pages: doc.page_count, authors: doc.authors.slice(0, 2).join(", ") })}
          </span>

          <span className="mx-1 hidden h-5 w-px bg-line sm:block" />

          <div className="flex items-center gap-1 rounded-xl border border-line bg-surface p-0.5">
            {MODES.map((item) => (
              <button
                key={item.key}
                className="btn btn-ghost !px-2.5 !py-1"
                data-active={mode === item.key}
                title={t(item.hint)}
                onClick={() => setMode(item.key)}
              >
                {t(item.label)}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-1.5">
            <input
              className="input !w-44"
              placeholder={t("搜索本文…")}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") cycleSearchHit(event.shiftKey ? -1 : 1);
              }}
            />
            {searchHits.length > 0 && (
              <span className="text-xs text-ink-2">
                {searchIndex + 1}/{searchHits.length}
                <button className="btn btn-ghost !px-1" onClick={() => cycleSearchHit(-1)}>
                  ↑
                </button>
                <button className="btn btn-ghost !px-1" onClick={() => cycleSearchHit(1)}>
                  ↓
                </button>
              </span>
            )}
          </div>

          <span className="mx-1 hidden h-5 w-px bg-line md:block" />

          <button
            ref={setChannelAnchor}
            className={`chip ${channelReady ? "chip-accent" : "chip-warn"} cursor-pointer`}
            onClick={() => setMenu(menu === "channel" ? "" : "channel")}
            title={activeStatus?.detail || t("选择模型通道")}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${channelReady ? "bg-ok" : "bg-warn"}`} />
            {channelLabel}
            {!channelReady && provider !== "off" && <span className="ml-1 underline">{t("如何启用？")}</span>}
          </button>

          <FloatingPanel
            anchor={channelAnchor}
            open={menu === "channel"}
            onClose={() => setMenu("")}
            width={340}
          >
            <div className="mb-2 font-medium">{t("模型通道 · 场景分工")}</div>
            <ChannelOption
              title={t("本地模型")}
              badge={t("免费 · 离线 · 数据不出本机")}
              detail={localStatus?.detail || t("检测中…")}
              available={Boolean(localStatus?.available)}
              active={provider === "local"}
              onClick={() => void chooseChannel("local")}
              onGuide={() => {
                setMenu("");
                setGuideFor("local");
              }}
              note={t("长难句与专业术语建议人工复核，界面会标出可疑段落")}
            />
            <ChannelOption
              title={t("云端模型")}
              badge={t("更准确 · 按 token 计费")}
              detail={cloudStatus?.detail || t("检测中…")}
              available={Boolean(cloudStatus?.available)}
              active={provider === "cloud"}
              onClick={() => void chooseChannel("cloud")}
              onGuide={() => {
                setMenu("");
                setGuideFor("cloud");
              }}
              note={t("翻译前会给出预计 token 与费用；不可用时可切回本地")}
            />
            <ChannelOption
              title={t("关闭 AI（纯阅读）")}
              badge={t("零 token · 零网络")}
              detail={t("只解析与阅读，翻译/总结/问答入口置灰")}
              available
              active={provider === "off"}
              onClick={() => void chooseChannel("off")}
            />
            <div className="mt-2 flex gap-1">
              <button className="btn flex-1 justify-center" onClick={() => setGuideFor(provider === "cloud" ? "cloud" : "local")}>
                {t("环境搭建引导")}
              </button>
              <button className="btn flex-1 justify-center" onClick={() => navigate("#/settings")}>
                {t("打开设置")}
              </button>
            </div>
          </FloatingPanel>

          <select
            className="select !w-28"
            value={lang}
            onChange={(event) => setLang(event.target.value)}
            title={t("目标语言")}
          >
            {LANGS.map((item) => (
              <option key={item.key} value={item.key}>
                {t(item.label)}
              </option>
            ))}
          </select>

          <button
            className="btn btn-primary"
            disabled={provider === "off" || busy}
            onClick={() => (channelReady ? void translate() : setGuideFor(provider === "cloud" ? "cloud" : "local"))}
            onMouseEnter={() => {
              if (channelReady) void runEstimate();
            }}
            title={
              provider === "off"
                ? t("AI 功能已关闭，请在通道菜单中启用")
                : !channelReady
                  ? t("当前通道不可用：点击查看启用步骤")
                  : provider === "local"
                    ? estimate
                      ? t("本地模型：免费离线，预计约 {minutes} 分钟", { minutes: Math.ceil(estimate.local_eta_seconds / 60) })
                      : t("本地模型翻译：免费、离线")
                    : estimate
                      ? t("云端：预计 {tokens} token ≈ ¥{cost}", { tokens: estimate.estimated_tokens_in + estimate.estimated_tokens_out, cost: estimate.estimated_cost_cny })
                      : t("云端翻译：更快更准，按 token 计费")
            }
          >
            {busy && task?.kind === "translate"
              ? t("翻译中 {done}/{total}", { done: task.done, total: task.total || "?" })
              : channelReady
                ? t("翻译全文")
                : t("启用通道")}
          </button>

          <div className="flex items-center gap-1">
            <button
              className="btn"
              data-active={dockOpen && dockTab === "summary"}
              onClick={() => toggleDock("summary")}
            >
              {t("要点")}
            </button>
            <button
              className="btn"
              data-active={dockOpen && dockTab === "chat"}
              onClick={() => toggleDock("chat")}
            >
              {t("问答")}
            </button>
            <button className="btn" onClick={() => setDockTab("notes")}>
              {t("笔记")}
            </button>
            <button className="btn" onClick={() => setDockTab("quality")}>
              {t("解析质量")}
            </button>
          </div>

          <button
            ref={setExportAnchor}
            className="btn"
            onClick={() => setMenu(menu === "export" ? "" : "export")}
          >
            {t("导出")}
          </button>
          <FloatingPanel
            anchor={exportAnchor}
            open={menu === "export"}
            onClose={() => setMenu("")}
            align="right"
            width={240}
          >
            {[
              { mode: "bilingual", label: "Markdown · 双语对照" },
              { mode: "translated", label: "Markdown · 仅译文" },
              { mode: "original", label: "Markdown · 仅原文" },
            ].map((item) => (
              <a
                key={item.mode}
                className="block rounded-lg px-2 py-1.5 hover:bg-accent-soft"
                href={api.exportUrl(doc.id, lang, item.mode)}
                onClick={() => setMenu("")}
              >
                {t(item.label)}
              </a>
            ))}
            <a
              className="block rounded-lg px-2 py-1.5 hover:bg-accent-soft"
              href={api.pdfUrl(doc.id)}
              target="_blank"
              rel="noreferrer"
              onClick={() => setMenu("")}
            >
              {t("原始 PDF")}
            </a>
          </FloatingPanel>
        </>
      )}

      <div className="ml-auto flex items-center gap-1">
        {usage && usage.cloud_tokens_out + usage.cloud_tokens_in > 0 && (
          <span className="chip" title={t("云端累计用量（本地通道不消耗 token）")}>
            {t("云端 {tokens} tok · ¥{cost}", {
              tokens: usage.cloud_tokens_in + usage.cloud_tokens_out,
              cost: usage.cloud_estimated_cost_cny.toFixed(3),
            })}
          </span>
        )}
        <button
          className="btn btn-ghost"
          title={t("界面语言 / Interface language")}
          onClick={() => setUiLang(uiLang === "zh" ? "en" : "zh")}
        >
          {uiLang === "en" ? "EN" : "中"}
        </button>
        <button
          className="btn btn-ghost"
          title={t("切换主题（跟随系统 → 浅色 → 深色）")}
          onClick={() => setTheme(theme === "system" ? "light" : theme === "light" ? "dark" : "system")}
        >
          {theme === "system" ? "◐" : theme === "light" ? "☀" : "☾"}
        </button>
        <button className="btn btn-ghost" onClick={() => navigate("#/settings")} title={t("设置")}>
          ⚙
        </button>
      </div>

      {busy && (
        <div className="w-full">
          <ProgressLine
            done={task?.done ?? 0}
            total={task?.total ?? 0}
            message={task?.message || t("处理中…")}
            provider={task?.provider || provider}
          />
        </div>
      )}

      {guideFor && <SetupGuidePanel channel={guideFor} onClose={() => setGuideFor(null)} />}
    </header>
  );
}

function ChannelOption(props: {
  title: string;
  badge: string;
  detail: string;
  available: boolean;
  active: boolean;
  note?: string;
  onClick: () => void;
  onGuide?: () => void;
}) {
  const t = useT();
  return (
    <div
      className={`mb-1.5 rounded-xl border p-2 transition ${
        props.active ? "border-accent-strong bg-accent-soft" : "border-line hover:bg-accent-soft/60"
      }`}
    >
      <button className="w-full text-left" onClick={props.onClick}>
        <div className="flex items-center justify-between gap-2">
          <span className="font-medium">{props.title}</span>
          <span className={`chip ${props.available ? "chip-ok" : "chip-warn"}`}>
            {props.available ? t("可用") : t("不可用")}
          </span>
        </div>
        <div className="mt-0.5 text-xs text-ink-2">{props.badge}</div>
        <div className="mt-0.5 text-xs text-ink-3">{props.detail}</div>
        {props.note && <div className="mt-1 text-[11px] text-ink-3">{props.note}</div>}
      </button>
      {!props.available && props.onGuide && (
        <button className="btn mt-1.5 w-full justify-center !text-[11px]" onClick={props.onGuide}>
          {t("查看启用步骤（下载 / 部署引导）")}
        </button>
      )}
    </div>
  );
}

function ProgressLine(props: { done: number; total: number; message: string; provider: string }) {
  const t = useT();
  const percent = props.total ? Math.round((props.done / props.total) * 100) : 8;
  return (
    <div className="flex items-center gap-2 px-1 pb-0.5 text-xs text-ink-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-paper-3">
        <div
          className="h-full rounded-full bg-accent-strong transition-all"
          style={{ width: `${Math.min(100, percent)}%` }}
        />
      </div>
      <span className="truncate max-w-[52ch]">{props.message}</span>
      <span className="chip">{props.provider === "local" ? t("本地") : t("云端")}</span>
    </div>
  );
}
