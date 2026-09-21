import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { DocBlock } from "../api/types";
import { useT } from "../i18n";
import { useApp } from "../store";

const TABS = [
  { key: "summary", label: "要点" },
  { key: "chat", label: "问答" },
  { key: "notes", label: "笔记" },
  { key: "glossary", label: "术语表" },
  { key: "quality", label: "解析质量" },
] as const;

export function Dock() {
  const open = useApp((s) => s.dockOpen);
  const tab = useApp((s) => s.dockTab);
  const setDockTab = useApp((s) => s.setDockTab);
  const toggleDock = useApp((s) => s.toggleDock);
  const t = useT();

  if (!open) {
    return (
      <div className="flex w-9 shrink-0 flex-col items-center gap-2 border-l border-line bg-paper-2/60 py-3">
        <button className="btn btn-ghost !px-1.5" onClick={() => toggleDock()} title={t("展开侧面板")}>
          ‹
        </button>
      </div>
    );
  }

  return (
    <aside className="flex w-[360px] shrink-0 flex-col border-l border-line bg-paper-2/60">
      <div className="flex items-center gap-1 border-b border-line px-2 py-1.5">
        {TABS.map((item) => (
          <button
            key={item.key}
            className="btn btn-ghost !px-2 !py-1 !text-[12px]"
            data-active={tab === item.key}
            onClick={() => setDockTab(item.key)}
          >
            {t(item.label)}
          </button>
        ))}
        <button className="btn btn-ghost ml-auto !px-1.5" onClick={() => toggleDock()} title={t("收起")}>
          ›
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === "summary" && <SummaryTab />}
        {tab === "chat" && <ChatTab />}
        {tab === "notes" && <NotesTab />}
        {tab === "glossary" && <GlossaryTab />}
        {tab === "quality" && <QualityTab />}
      </div>
    </aside>
  );
}

function SummaryTab() {
  const summary = useApp((s) => s.summary);
  const runSummary = useApp((s) => s.runSummary);
  const task = useApp((s) => s.task);
  const provider = useApp((s) => s.provider);
  const busy = task?.status === "running" && task.kind === "summary";
  const t = useT();

  return (
    <div className="text-sm">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button className="btn btn-primary" disabled={provider === "off" || busy} onClick={() => void runSummary(false)}>
          {busy ? t("生成中…") : summary ? t("重新生成要点") : t("生成结构化要点")}
        </button>
        {provider === "cloud" && <span className="chip chip-warn">{t("云端 · 按 token 计费")}</span>}
        {provider === "local" && <span className="chip chip-ok">{t("本地 · 免费离线")}</span>}
      </div>
      {provider === "off" && (
        <p className="mb-3 rounded-xl border border-line bg-surface p-2 text-xs leading-relaxed text-ink-2">
          {t(
            "AI 功能已关闭（纯阅读模式）。在顶栏的通道菜单或设置里启用本地/云端模型后即可生成要点。",
          )}
        </p>
      )}
      {summary ? (
        <div className="prose-sm leading-relaxed [&_h2]:mt-3 [&_h2]:mb-1 [&_h2]:text-[13px] [&_h2]:font-semibold [&_li]:ml-4 [&_li]:list-disc">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{summary}</ReactMarkdown>
        </div>
      ) : (
        <p className="text-xs leading-relaxed text-ink-3">
          {t(
            "生成后会得到：研究问题 / 方法与技术路线 / 数据与实验设置 / 主要结论 / 创新点 / 局限 / 关键数据 / 可复用之处， 每个结论尽量带具体数字。可导出为 Markdown。",
          )}
        </p>
      )}
    </div>
  );
}

function ChatTab() {
  const chat = useApp((s) => s.chat);
  const ask = useApp((s) => s.ask);
  const clearChat = useApp((s) => s.clearChat);
  const provider = useApp((s) => s.provider);
  const activeBlockId = useApp((s) => s.activeBlockId);
  const setActiveBlock = useApp((s) => s.setActiveBlock);
  const [question, setQuestion] = useState("");
  const [useSelection, setUseSelection] = useState(true);
  const t = useT();

  const send = () => {
    if (!question.trim()) return;
    void ask(question.trim(), useSelection && activeBlockId ? [activeBlockId] : undefined);
    setQuestion("");
  };

  return (
    <div className="flex h-full flex-col text-sm">
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto">
        {chat.length === 0 && (
          <p className="text-xs leading-relaxed text-ink-3">
            {t(
              "基于本文内容作答，并给出处（段落 + 页码）；文中没有依据时会明确说明「文中未提及」。 点击任意段落后再提问，会优先以该段落为依据。",
            )}
          </p>
        )}
        {chat.map((message, index) => (
          <div
            key={index}
            className={`rounded-xl border p-2 leading-relaxed ${
              message.role === "user" ? "border-line bg-surface" : "border-accent-strong bg-accent-soft/70"
            }`}
          >
            <div className="mb-1 text-[11px] text-ink-3">
              {message.role === "user" ? t("我") : t("助手")}
              {message.role === "assistant" && message.grounded === false && (
                <span className="chip chip-warn ml-1">{t("文中未提及")}</span>
              )}
            </div>
            <div className="whitespace-pre-wrap">{message.text}</div>
            {message.evidence && message.evidence.length > 0 && (
              <div className="mt-2 space-y-1">
                {message.evidence.map((item) => (
                  <button
                    key={`${item.block_id}-${item.quote.slice(0, 8)}`}
                    className="block w-full rounded-lg border border-line bg-surface/70 p-1.5 text-left text-[11px] hover:bg-accent-soft"
                    onClick={() => setActiveBlock(item.block_id)}
                  >
                    <span className="text-ink-3">{t("第 {page} 页", { page: item.page + 1 })} ·</span>{" "}
                    {item.quote}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="mt-2 border-t border-line pt-2">
        <label className="mb-1 flex items-center gap-1.5 text-[11px] text-ink-3">
          <input
            type="checkbox"
            checked={useSelection && Boolean(activeBlockId)}
            disabled={!activeBlockId}
            onChange={(event) => setUseSelection(event.target.checked)}
          />
          {activeBlockId ? t("优先依据当前选中段落") : t("先在正文中点选一段可限定依据")}
        </label>
        <textarea
          className="textarea"
          rows={2}
          placeholder={t("例如：这篇论文的核心创新点是什么？")}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) send();
          }}
        />
        <div className="mt-1 flex items-center justify-between">
          <span className="text-[11px] text-ink-3">
            {provider === "off"
              ? t("AI 已关闭")
              : provider === "local"
                ? t("本地模型 · 免费离线")
                : t("云端模型 · 按量计费")}
          </span>
          <div className="flex gap-1">
            <button className="btn" onClick={clearChat}>
              {t("清空")}
            </button>
            <button className="btn btn-primary" disabled={provider === "off"} onClick={send}>
              {t("提问")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function NotesTab() {
  const notes = useApp((s) => s.notes);
  const removeNote = useApp((s) => s.removeNote);
  const setActiveBlock = useApp((s) => s.setActiveBlock);
  const lang = useApp((s) => s.lang);
  const doc = useApp((s) => s.doc);
  const t = useT();

  return (
    <div className="space-y-2 text-sm">
      <div className="flex items-center justify-between">
        <span className="text-xs text-ink-3">{t("共 {count} 条（保存在本地）", { count: notes.length })}</span>
        {doc && (
          <a className="btn" href={`/api/documents/${doc.id}/export?lang=${lang}&mode=bilingual`}>
            {t("导出含笔记")}
          </a>
        )}
      </div>
      {notes.length === 0 && (
        <p className="text-xs leading-relaxed text-ink-3">
          {t("悬停任意段落点击「笔记」即可添加批注；笔记会随 Markdown 一起导出。")}
        </p>
      )}
      {notes.map((note) => (
        <div key={note.id} className="rounded-xl border border-line bg-surface p-2">
          <button className="w-full text-left text-[11px] text-ink-3" onClick={() => setActiveBlock(note.block_id)}>
            {t("跳到该段落")}
          </button>
          <div className="mt-1 whitespace-pre-wrap">{note.comment}</div>
          <div className="mt-1 border-l-2 border-accent-strong pl-2 text-[11px] text-ink-3">{note.quote}</div>
          <div className="mt-1 flex justify-end">
            <button className="btn btn-ghost !px-1.5 !py-0.5 !text-[11px] text-danger" onClick={() => void removeNote(note.id)}>
              {t("删除")}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

function GlossaryTab() {
  const glossary = useApp((s) => s.glossary);
  const saveTerm = useApp((s) => s.saveTerm);
  const removeTerm = useApp((s) => s.removeTerm);
  const buildGlossary = useApp((s) => s.buildGlossary);
  const provider = useApp((s) => s.provider);
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const t = useT();

  return (
    <div className="space-y-2 text-sm">
      <p className="text-xs leading-relaxed text-ink-3">
        {t("术语表决定全文译法一致性，翻译时会强制注入。修改后对新翻译立即生效，也可对个别段落点「重译」。")}
      </p>
      <div className="flex gap-1">
        <button
          className="btn"
          disabled={provider === "off" || busy}
          onClick={() => {
            setBusy(true);
            void buildGlossary().finally(() => setBusy(false));
          }}
        >
          {busy ? t("抽取中…") : t("自动抽取术语")}
        </button>
        <span className="chip">{t("{count} 条", { count: glossary.length })}</span>
      </div>
      <div className="grid grid-cols-[1fr_1fr_auto] gap-1">
        <input
          className="input"
          placeholder={t("原文术语")}
          value={source}
          onChange={(e) => setSource(e.target.value)}
        />
        <input
          className="input"
          placeholder={t("译法")}
          value={target}
          onChange={(e) => setTarget(e.target.value)}
        />
        <button
          className="btn"
          onClick={() => {
            if (!source.trim() || !target.trim()) return;
            void saveTerm(source.trim(), target.trim());
            setSource("");
            setTarget("");
          }}
        >
          {t("添加")}
        </button>
      </div>
      <div className="divide-y divide-line rounded-xl border border-line bg-surface">
        {glossary.map((term) => (
          <div key={term.id} className="flex items-center gap-2 px-2 py-1.5 text-[12.5px]">
            <span className="flex-1 truncate" title={term.source}>
              {term.source}
            </span>
            <span className="text-ink-3">→</span>
            <span className="flex-1 truncate font-medium" title={term.target}>
              {term.target}
            </span>
            {term.locked && <span className="chip !py-0 !text-[10px]">{t("手动")}</span>}
            <button className="btn btn-ghost !px-1 !py-0 !text-[11px] text-danger" onClick={() => void removeTerm(term.id)}>
              ✕
            </button>
          </div>
        ))}
        {glossary.length === 0 && <div className="px-2 py-3 text-center text-xs text-ink-3">{t("暂无术语")}</div>}
      </div>
    </div>
  );
}

function QualityTab() {
  const doc = useApp((s) => s.doc);
  const blocks = useApp((s) => s.blocks);
  const provider = useApp((s) => s.provider);
  const stats = useMemo(() => summarizeBlocks(blocks), [blocks]);
  const report = doc?.parse_report;
  const t = useT();

  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs leading-relaxed text-ink-3">
        {t("解析质量与翻译质量都如实呈现：不确定的地方宁可标出来，也不假装完美。")}
      </p>

      {report && (
        <div className="rounded-xl border border-line bg-surface p-2">
          <div className="mb-1 flex items-center gap-2 text-xs font-medium">
            {t("解析自检")}
            <span className="chip">{t(channelLabel(report.channel))}</span>
          </div>
          <Row label={t("版面判定")} value={t(alignmentLabel(report.alignment))} />
          <Row label={t("段落数")} value={`${report.paragraph_count}`} />
          <Row
            label={t("图表 / 表格 / 公式")}
            value={`${report.figure_count} / ${report.table_count} / ${report.formula_count}`}
          />
          <Row label={t("文本覆盖率")} value={`${(report.text_coverage * 100).toFixed(1)}%`} />
          <Row label={t("乱码率")} value={`${(report.garbage_ratio * 100).toFixed(2)}%`} />
          <Row label={t("解析耗时")} value={`${report.duration_ms} ms`} />
          {report.ocr_pages > 0 && (
            <>
              <Row label={t("OCR 处理页数")} value={t("{count} 页", { count: report.ocr_pages })} />
              <Row
                label={t("OCR 平均置信度")}
                value={`${(report.ocr_confidence * 100).toFixed(1)}%`}
              />
              <p className="mt-1 text-[11px] leading-relaxed text-warn">
                {t(
                  "OCR 结果是识别重建，标点、连字符与个别字符可能与原页面不一致， 关键数字请对照「原版页」核对。",
                )}
              </p>
            </>
          )}
          {report.warnings.length > 0 && (
            <ul className="mt-1 list-disc pl-4 text-[11px] text-warn">
              {report.warnings.slice(0, 6).map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="rounded-xl border border-line bg-surface p-2">
        <div className="mb-1 text-xs font-medium">
          {t("翻译质量（当前通道：{channel}）", { channel: provider })}
        </div>
        <Row label={t("已翻译段落")} value={`${stats.translated}`} />
        <Row label={t("正常")} value={`${stats.ok}`} />
        <Row label={t("待复核（校验未通过）")} value={`${stats.suspect}`} />
        <Row label={t("失败")} value={`${stats.failed}`} />
        {stats.suspect + stats.failed > 0 && (
          <p className="mt-1 text-[11px] leading-relaxed text-ink-3">
            {t(
              "可疑段落已在正文左侧以黄色标记。「待复核」通常意味着数字、引用或占位符数量与原文不一致， 建议对照「原版页」核对，或用云端通道重译该段。",
            )}
          </p>
        )}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2 py-0.5 text-[12.5px]">
      <span className="text-ink-3">{label}</span>
      <span>{value}</span>
    </div>
  );
}

function alignmentLabel(alignment: string): string {
  return alignment === "double"
    ? "双栏"
    : alignment === "single"
      ? "单栏"
      : alignment === "mixed"
        ? "混排"
        : "未知";
}

function channelLabel(channel: string): string {
  if (channel === "ocr") return "OCR 识别";
  if (channel === "text-layer+ocr") return "文本层 + OCR";
  return "文本层";
}

function summarizeBlocks(blocks: DocBlock[]) {
  let translated = 0;
  let ok = 0;
  let suspect = 0;
  let failed = 0;
  for (const block of blocks) {
    const variants = Object.values(block.translations);
    if (!variants.some((text) => text.trim())) continue;
    translated += 1;
    const meta = Object.values(block.translation_meta)[0];
    if (meta?.quality === "suspect") suspect += 1;
    else if (meta?.quality === "failed") failed += 1;
    else ok += 1;
  }
  return { translated, ok, suspect, failed };
}
