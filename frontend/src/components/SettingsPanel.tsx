import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { OcrMode } from "../api/types";
import { navigate } from "../hooks/useHashRoute";
import { useT } from "../i18n";
import { useApp } from "../store";

export function SettingsPanel() {
  const t = useT();
  const settings = useApp((s) => s.settings);
  const providers = useApp((s) => s.providers);
  const environment = useApp((s) => s.environment);
  const usage = useApp((s) => s.usage);
  const theme = useApp((s) => s.theme);
  const setTheme = useApp((s) => s.setTheme);
  const fontScale = useApp((s) => s.fontScale);
  const setFontScale = useApp((s) => s.setFontScale);
  const saveSettings = useApp((s) => s.saveSettings);
  const resetUsage = useApp((s) => s.resetUsage);
  const toast = useApp((s) => s.toast);
  const ocrMode = useApp((s) => s.ocrMode);
  const setOcrMode = useApp((s) => s.setOcrMode);

  const [form, setForm] = useState({
    local_base_url: "",
    local_model: "",
    cloud_base_url: "",
    cloud_model: "",
    cloud_api_key: "",
    chunk_token_budget: 1200,
    context_paragraphs: 2,
    token_budget_per_doc: 0,
    local_concurrency: 1,
    cloud_concurrency: 4,
    quality_retry_limit: 1,
  });
  const [models, setModels] = useState<string[]>([]);
  const [pull, setPull] = useState<{ model: string; text: string; percent: number | null } | null>(null);

  useEffect(() => {
    if (!settings) return;
    setForm({
      local_base_url: settings.local_base_url,
      local_model: settings.local_model,
      cloud_base_url: settings.cloud_base_url,
      cloud_model: settings.cloud_model,
      cloud_api_key: "",
      chunk_token_budget: settings.chunk_token_budget,
      context_paragraphs: settings.context_paragraphs,
      token_budget_per_doc: settings.token_budget_per_doc,
      local_concurrency: settings.local_concurrency,
      cloud_concurrency: settings.cloud_concurrency,
      quality_retry_limit: settings.quality_retry_limit,
    });
  }, [settings]);

  useEffect(() => {
    void api.models().then((res) => setModels(res.installed)).catch(() => setModels([]));
  }, [pull]);

  const local = providers.find((p) => p.name === "local");
  const cloud = providers.find((p) => p.name === "cloud");

  const startPull = (model: string) => {
    if (!model.trim()) {
      toast("warn", t("请先填写模型名称，例如 qwen3:8b"));
      return;
    }
    setPull({ model, text: t("连接本地推理服务…"), percent: null });
    api.pullModel(
      model,
      (event) => {
        const status = String(event.status ?? "");
        const total = Number(event.total ?? 0);
        const completed = Number(event.completed ?? 0);
        const percent = total > 0 ? Math.round((completed / total) * 100) : null;
        if (typeof event.error === "string") {
          setPull({ model, text: t("下载失败：{error}", { error: event.error }), percent: null });
          return;
        }
        setPull({ model, text: status || t("下载中"), percent });
      },
      () => {
        setPull((current) => (current ? { ...current, text: current.text || t("完成") } : null));
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-center overflow-y-auto bg-ink/50 p-4 backdrop-blur-sm">
      <div className="card my-4 w-full max-w-3xl p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">{t("设置")}</h2>
          <button className="btn" onClick={() => navigate("#/")}>
            {t("关闭")}
          </button>
        </div>

        <Section
          title={t("模型通道")}
          note={t("本地=免费离线；云端=更准但按 token 计费。两种通道可随时切换，术语表与已翻译段落共用。")}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <StatusCard
              title={t("本地模型（Ollama）")}
              available={Boolean(local?.available)}
              detail={local?.detail || t("检测中…")}
              lines={[
                t("端点 {url}", { url: local?.base_url || "-" }),
                t("当前模型 {model}", { model: local?.model || "-" }),
              ]}
            />
            <StatusCard
              title={t("云端模型（OpenAI 兼容）")}
              available={Boolean(cloud?.available)}
              detail={cloud?.detail || t("检测中…")}
              lines={[
                t("端点 {url}", { url: cloud?.base_url || "-" }),
                t("当前模型 {model}", { model: cloud?.model || "-" }),
              ]}
            />
          </div>
        </Section>

        <Section
          title={t("本地模型管理")}
          note={t("首次使用需要一次性联网下载模型权重（约 4~5GB）；下载完成后即可全程离线使用。")}
        >
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-xs text-ink-2">
              {t("推理服务端点")}
              <input
                className="input mt-1"
                value={form.local_base_url}
                onChange={(event) => setForm({ ...form, local_base_url: event.target.value })}
              />
            </label>
            <label className="text-xs text-ink-2">
              {t("模型名称")}
              <input
                className="input mt-1"
                value={form.local_model}
                onChange={(event) => setForm({ ...form, local_model: event.target.value })}
                placeholder="qwen3:8b"
              />
            </label>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button className="btn btn-primary" onClick={() => startPull(form.local_model)}>
              {t("下载 / 更新此模型")}
            </button>
            <button
              className="btn"
              onClick={() => {
                void api
                  .models()
                  .then((res) => setModels(res.installed))
                  .catch(() => undefined);
              }}
            >
              {t("刷新已安装列表")}
            </button>
            <span className="text-xs text-ink-3">
              {models.length
                ? t("已安装：{models}", { models: models.join(", ") })
                : t("未检测到已安装模型")}
            </span>
          </div>

          {pull && (
            <div className="mt-2 rounded-xl border border-line bg-paper-2 p-2 text-xs">
              <div className="flex items-center justify-between">
                <span>
                  {pull.model} · {pull.text}
                </span>
                <span>{pull.percent !== null ? `${pull.percent}%` : ""}</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-paper-3">
                <div
                  className="h-full bg-accent-strong transition-all"
                  style={{ width: `${pull.percent ?? 15}%` }}
                />
              </div>
            </div>
          )}

          <details className="mt-3 text-xs text-ink-2">
            <summary className="cursor-pointer">{t("无外网环境？离线导入模型包")}</summary>
            <p className="mt-2 leading-relaxed">
              {t("在能联网的机器上执行")}{" "}
              <code className="font-mono">ollama pull {form.local_model || "qwen3:8b"}</code>
              {t("，把 Ollama 的模型目录（Windows:")}{" "}
              <code className="font-mono">%USERPROFILE%\.ollama\models</code>
              {t("）整体拷贝到本机同一路径，然后重启本地推理服务即可，全程无需联网。")}
            </p>
          </details>
        </Section>

        <Section
          title={t("扫描件 OCR（本地离线）")}
          note={t("没有文本层的扫描 PDF 需要 OCR 才能阅读与翻译。RapidOCR 在 CPU 上运行，完全离线，约 1~3 秒/页；它不会与本地模型抢显存。")}
        >
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className={`chip ${environment?.ocr?.available ? "chip-ok" : "chip-warn"}`}>
              {environment?.ocr?.available ? t("OCR 引擎就绪") : t("OCR 不可用")}
            </span>
            <span className="text-ink-3">{environment?.ocr?.detail}</span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
            <span>{t("处理方式")}</span>
            <select
              className="select !w-56"
              value={ocrMode}
              onChange={(event) => setOcrMode(event.target.value as OcrMode)}
            >
              <option value="auto">{t("自动：仅对扫描页做 OCR（推荐）")}</option>
              <option value="force">{t("强制：所有页面都过 OCR")}</option>
              <option value="off">{t("关闭：只用文本层")}</option>
            </select>
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-ink-3">
            {t("切换后立即生效，下次上传生效。OCR 结果会在解析质量里标注处理页数与置信度，")}{" "}
            {t("并在质量分中体现不确定性 —— 建议对照「原版页」核对关键数字。")}
          </p>
        </Section>

        <Section
          title={t("云端 API（可选）")}
          note={t("密钥只保存在本机后端，不会写入前端或仓库，界面仅显示是否已配置。")}
        >
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-xs text-ink-2">
              Base URL
              <input
                className="input mt-1"
                value={form.cloud_base_url}
                onChange={(event) => setForm({ ...form, cloud_base_url: event.target.value })}
              />
            </label>
            <label className="text-xs text-ink-2">
              {t("模型")}
              <input
                className="input mt-1"
                value={form.cloud_model}
                onChange={(event) => setForm({ ...form, cloud_model: event.target.value })}
              />
            </label>
          </div>
          <label className="mt-2 block text-xs text-ink-2">
            API Key{" "}
            {settings?.cloud_api_key_set && <span className="chip chip-ok ml-1">{t("已配置")}</span>}
            <input
              className="input mt-1"
              type="password"
              value={form.cloud_api_key}
              placeholder={settings?.cloud_api_key_set ? t("留空表示不修改") : "sk-…"}
              onChange={(event) => setForm({ ...form, cloud_api_key: event.target.value })}
            />
          </label>
        </Section>

        <Section
          title={t("翻译与质量")}
          note={t("本地通道并发固定为 1（显存约束），并且必须开启质量校验——本地模型在数字与引用上更容易出错。")}
        >
          <div className="grid gap-2 sm:grid-cols-3">
            <NumberField
              label={t("分块 token 上限")}
              value={form.chunk_token_budget}
              onChange={(value) => setForm({ ...form, chunk_token_budget: value })}
              hint={t("本地模型建议 800~1200")}
            />
            <NumberField
              label={t("上下文段落数")}
              value={form.context_paragraphs}
              onChange={(value) => setForm({ ...form, context_paragraphs: value })}
              hint={t("用于减少指代错误")}
            />
            <NumberField
              label={t("质量重译次数")}
              value={form.quality_retry_limit}
              onChange={(value) => setForm({ ...form, quality_retry_limit: value })}
            />
            <NumberField
              label={t("本地并发")}
              value={form.local_concurrency}
              onChange={(value) => setForm({ ...form, local_concurrency: value })}
              hint={t("显存不足时保持 1")}
            />
            <NumberField
              label={t("云端并发")}
              value={form.cloud_concurrency}
              onChange={(value) => setForm({ ...form, cloud_concurrency: value })}
            />
            <NumberField
              label={t("单篇 token 预算")}
              value={form.token_budget_per_doc}
              onChange={(value) => setForm({ ...form, token_budget_per_doc: value })}
              hint={t("0 表示不限制")}
            />
          </div>
        </Section>

        <Section title={t("用量与费用")} note={t("云端按 token 计费；本地只统计处理量与耗时。")}>
          <div className="grid gap-2 text-sm sm:grid-cols-4">
            <Metric label={t("云端输入 token")} value={usage?.cloud_tokens_in ?? 0} />
            <Metric label={t("云端输出 token")} value={usage?.cloud_tokens_out ?? 0} />
            <Metric label={t("预估费用")} value={`¥ ${(usage?.cloud_estimated_cost_cny ?? 0).toFixed(3)}`} />
            <Metric label={t("本地处理段落")} value={usage?.local_blocks_translated ?? 0} />
          </div>
          <button className="btn mt-2" onClick={() => void resetUsage()}>
            {t("清零统计")}
          </button>
        </Section>

        <Section title={t("阅读与外观")}>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span>{t("主题")}</span>
            <select className="select !w-32" value={theme} onChange={(e) => setTheme(e.target.value as never)}>
              <option value="system">{t("跟随系统")}</option>
              <option value="light">{t("米白浅色")}</option>
              <option value="dark">{t("夜间")}</option>
            </select>
            <span className="ml-2">{t("字号 {percent}%", { percent: Math.round(fontScale * 100) })}</span>
            <input
              type="range"
              min={0.85}
              max={1.4}
              step={0.05}
              value={fontScale}
              onChange={(e) => setFontScale(Number(e.target.value))}
            />
          </div>
        </Section>

        <Section title={t("离线状态")}>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className={`chip ${environment?.internet ? "chip-ok" : "chip-warn"}`}>
              {environment?.internet ? t("网络：已连接") : t("网络：离线")}
            </span>
            <span className="chip chip-ok">{t("解析 / 阅读 / 笔记：始终离线可用")}</span>
            <span className={`chip ${local?.available ? "chip-ok" : "chip-warn"}`}>
              {local?.available ? t("本地翻译：可用（零 token）") : t("本地翻译：需先下载模型")}
            </span>
            <span className={`chip ${cloud?.available ? "chip-ok" : "chip-warn"}`}>
              {cloud?.available ? t("云端翻译：可用（按量计费）") : t("云端翻译：不可用")}
            </span>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-ink-3">
            {t("本软件不上报任何使用数据；除首次下载模型权重与可选的云端调用外，运行期不发任何外部请求。")}
          </p>
        </Section>

        <div className="mt-4 flex justify-end gap-2">
          <button
            className="btn btn-primary"
            onClick={() =>
              void saveSettings({
                local_base_url: form.local_base_url,
                local_model: form.local_model,
                cloud_base_url: form.cloud_base_url,
                cloud_model: form.cloud_model,
                ...(form.cloud_api_key ? { cloud_api_key: form.cloud_api_key } : {}),
                chunk_token_budget: form.chunk_token_budget,
                context_paragraphs: form.context_paragraphs,
                token_budget_per_doc: form.token_budget_per_doc,
                local_concurrency: form.local_concurrency,
                cloud_concurrency: form.cloud_concurrency,
                quality_retry_limit: form.quality_retry_limit,
              })
            }
          >
            {t("保存设置")}
          </button>
        </div>
      </div>
    </div>
  );
}

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-4 rounded-xl border border-line bg-paper-2/50 p-3">
      <h3 className="text-sm font-semibold">{title}</h3>
      {note && <p className="mt-1 mb-2 text-xs leading-relaxed text-ink-3">{note}</p>}
      <div className={note ? "" : "mt-2"}>{children}</div>
    </section>
  );
}

function StatusCard({
  title,
  available,
  detail,
  lines,
}: {
  title: string;
  available: boolean;
  detail: string;
  lines: string[];
}) {
  const t = useT();
  return (
    <div className="rounded-xl border border-line bg-surface p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{title}</span>
        <span className={`chip ${available ? "chip-ok" : "chip-warn"}`}>
          {available ? t("可用") : t("不可用")}
        </span>
      </div>
      <div className="mt-1 text-xs text-ink-2">{detail}</div>
      {lines.map((line) => (
        <div key={line} className="text-[11px] text-ink-3">
          {line}
        </div>
      ))}
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  hint?: string;
}) {
  return (
    <label className="text-xs text-ink-2">
      {label}
      <input
        className="input mt-1"
        type="number"
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      {hint && <span className="text-[11px] text-ink-3">{hint}</span>}
    </label>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-2">
      <div className="text-[11px] text-ink-3">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  );
}
