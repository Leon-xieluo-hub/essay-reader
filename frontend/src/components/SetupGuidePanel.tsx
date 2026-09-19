import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "../api/client";
import type { ProviderKey, SetupGuide } from "../api/types";
import { useApp } from "../store";

/**
 * Turns "this channel is unavailable" into a concrete recovery path:
 * download the installer, pull the model, or configure a cloud key — with the
 * official links and the exact commands shown inline.
 *
 * Rendered through a portal: the top bar uses `backdrop-filter`, which makes it
 * a containing block for `position: fixed`. Mounted inside the header the modal
 * would be positioned relative to the bar (stretching downwards) instead of the
 * viewport, so it could never sit in the middle of the screen.
 */
export function SetupGuidePanel({
  channel,
  onClose,
}: {
  channel: ProviderKey;
  onClose: () => void;
}) {
  const toast = useApp((s) => s.toast);
  const setProvider = useApp((s) => s.setProvider);
  const saveSettings = useApp((s) => s.saveSettings);
  const settings = useApp((s) => s.settings);
  const [guide, setGuide] = useState<SetupGuide | null>(null);
  const [busy, setBusy] = useState("");
  const [progress, setProgress] = useState<{ text: string; percent: number | null } | null>(null);
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");

  const refresh = useCallback(async () => {
    try {
      const next = await api.setupGuide();
      setGuide(next);
      setModel((current) => current || next.local.model);
    } catch (error) {
      toast("error", (error as Error).message);
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const pullModel = () => {
    const target = model.trim() || guide?.local.model || "";
    if (!target) {
      toast("warn", "请填写要下载的模型名，例如 qwen3:8b");
      return;
    }
    setBusy("pull");
    setProgress({ text: `正在连接本地推理服务并下载 ${target}…`, percent: 0 });
    api.pullModel(
      target,
      (event) => {
        if (typeof event.error === "string") {
          setProgress({ text: `下载失败：${event.error}`, percent: null });
          return;
        }
        const total = Number(event.total ?? 0);
        const completed = Number(event.completed ?? 0);
        setProgress({
          text: String(event.status ?? "下载中"),
          percent: total > 0 ? Math.round((completed / total) * 100) : null,
        });
      },
      async () => {
        setBusy("");
        await refresh();
        setProgress((current) =>
          current ? { ...current, text: "下载流程结束，可点击「重新检测」确认" } : null,
        );
      },
    );
  };

  const downloadInstaller = () => {
    const url = guide?.links.ollama_installer ?? "";
    if (!url) return;
    setBusy("download");
    setProgress({ text: "正在下载安装包…", percent: 0 });
    api.downloadOllama(
      url,
      (event) => {
        if (typeof event.error === "string") {
          setProgress({ text: `下载失败：${event.error}`, percent: null });
          return;
        }
        if (event.done) {
          setProgress({
            text: `已保存到 ${String(event.path ?? "")}（${Math.round(Number(event.size ?? 0) / 1048576)} MB）`,
            percent: 100,
          });
          return;
        }
        setProgress({ text: "正在下载安装包…", percent: Number(event.percent ?? 0) });
      },
      () => setBusy(""),
    );
  };

  const local = guide?.local;
  const cloud = guide?.cloud;

  return createPortal(
    <div
      className="fixed inset-0 flex items-center justify-center bg-ink/45 p-4 backdrop-blur-sm"
      style={{ zIndex: 400 }}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="card flex w-full max-w-2xl flex-col overflow-hidden"
        style={{ maxHeight: "min(86vh, 46rem)" }}
      >
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            <h2 className="text-base font-semibold">
              {channel === "cloud" ? "启用云端模型" : "启用本地模型"}
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-ink-3">
              翻译、要点与问答需要一条可用的模型通道。下面按依赖顺序给出每一步，
              完成后可随时回来点「重新检测」。
            </p>
          </div>
          <button className="btn shrink-0" onClick={onClose}>
            关闭
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {!guide && <p className="text-sm text-ink-2">正在检测环境…</p>}

          {guide && channel === "local" && local && (
            <ol className="space-y-3 text-sm">
              <Step
                index={1}
                title="安装本地推理引擎（Ollama）"
                state={local.binary_found ? "done" : "todo"}
                detail={
                  local.binary_found
                    ? `已检测到：${local.binary_path}`
                    : "尚未检测到 Ollama。可以一键下载官方安装包，或自行从官网下载。"
                }
              >
                {!local.binary_found && (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <button
                      className="btn btn-primary"
                      disabled={busy === "download"}
                      onClick={downloadInstaller}
                    >
                      {busy === "download" ? "下载中…" : "一键下载安装包"}
                    </button>
                    <a
                      className="btn"
                      href={guide.links.ollama_download}
                      target="_blank"
                      rel="noreferrer"
                    >
                      打开官网下载页
                    </a>
                    <span className="text-[11px] text-ink-3">
                      下载完成后双击安装；静默安装可用
                      <code className="mx-1 font-mono">{guide.commands.windows_install}</code>
                    </span>
                  </div>
                )}
              </Step>

              <Step
                index={2}
                title="启动推理服务"
                state={local.binary_found ? "todo" : "wait"}
                detail="安装完成后 Ollama 会常驻后台（托盘图标）。若未启动，运行 `ollama serve`。"
              >
                <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-ink-3">
                  <span>
                    当前端点：<code className="font-mono">{local.base_url}</code>
                  </span>
                  {local.detail && <span className="chip chip-warn">{local.detail}</span>}
                </div>
              </Step>

              <Step
                index={3}
                title="下载翻译模型"
                state={
                  local.installed_models.length ? "done" : local.binary_found ? "todo" : "wait"
                }
                detail={
                  local.installed_models.length
                    ? `已安装 ${local.installed_models.length} 个模型：${local.installed_models
                        .slice(0, 5)
                        .join(", ")}`
                    : "模型权重在应用内下载，全程离线可用；8GB 显存建议 8B 级 Q5/Q6 量化。"
                }
              >
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <input
                    className="input !w-52"
                    value={model}
                    placeholder="qwen3:8b"
                    onChange={(event) => setModel(event.target.value)}
                  />
                  <button className="btn btn-primary" disabled={busy === "pull"} onClick={pullModel}>
                    {busy === "pull" ? "下载中…" : "一键下载模型"}
                  </button>
                  <a
                    className="btn"
                    href={guide.links.ollama_models}
                    target="_blank"
                    rel="noreferrer"
                  >
                    浏览模型库
                  </a>
                </div>
                <p className="mt-1 text-[11px] text-ink-3">
                  命令行方式：<code className="font-mono">{guide.commands.pull_model}</code>
                </p>
              </Step>

              <Step
                index={4}
                title="切换通道并开始翻译"
                state={local.available ? "done" : "wait"}
                detail={
                  local.available
                    ? "本地通道已就绪：免费、离线、数据不出本机。"
                    : "三步完成后，本通道会变为可用。"
                }
              >
                <div className="mt-2 flex flex-wrap gap-2">
                  <button className="btn" onClick={() => void refresh()}>
                    重新检测
                  </button>
                  <button
                    className="btn btn-primary"
                    disabled={!local.available}
                    onClick={async () => {
                      await setProvider("local");
                      onClose();
                    }}
                  >
                    切换到本地模型
                  </button>
                </div>
              </Step>
            </ol>
          )}

          {guide && channel === "cloud" && cloud && (
            <div className="space-y-3 text-sm">
              <p className="text-xs leading-relaxed text-ink-3">
                云端通道兼容任何 OpenAI 格式接口（DeepSeek、OpenAI、自建中转均可）。
                密钥只保存在本机后端，界面不会回显，也不会写入仓库。
              </p>
              <label className="block text-xs text-ink-2">
                Base URL
                <input className="input mt-1" defaultValue={cloud.base_url} id="cloud-base-url" />
              </label>
              <label className="block text-xs text-ink-2">
                API Key {cloud.api_key_set && <span className="chip chip-ok ml-1">已配置</span>}
                <input
                  className="input mt-1"
                  type="password"
                  placeholder="sk-…"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                />
              </label>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  className="btn btn-primary"
                  disabled={!apiKey.trim()}
                  onClick={async () => {
                    const baseUrl = (document.getElementById("cloud-base-url") as HTMLInputElement)
                      ?.value;
                    await saveSettings({
                      ...(baseUrl ? { cloud_base_url: baseUrl } : {}),
                      cloud_api_key: apiKey.trim(),
                    });
                    setApiKey("");
                    await refresh();
                  }}
                >
                  保存并检测
                </button>
                <a className="btn" href={guide.links.deepseek_keys} target="_blank" rel="noreferrer">
                  获取 DeepSeek Key
                </a>
                <a
                  className="btn"
                  href={guide.links.openai_compatible_docs}
                  target="_blank"
                  rel="noreferrer"
                >
                  接口文档
                </a>
                <button className="btn" onClick={() => void refresh()}>
                  重新检测
                </button>
              </div>
              <p className="text-[11px] text-ink-3">
                当前模型：<code className="font-mono">{cloud.model}</code> ·{" "}
                {settings?.cloud_api_key_set ? "已保存密钥" : "尚未保存密钥"} · {cloud.detail}
              </p>
            </div>
          )}

          {progress && (
            <div className="mt-4 rounded-xl border border-line bg-paper-2 p-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate">{progress.text}</span>
                {progress.percent !== null && <span>{progress.percent}%</span>}
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-paper-3">
                <div
                  className="h-full bg-accent-strong transition-all"
                  style={{ width: `${progress.percent ?? 12}%` }}
                />
              </div>
            </div>
          )}
        </div>

        <div className="border-t border-line px-5 py-3">
          <p className="text-[11px] leading-relaxed text-ink-3">
            提示：解析、阅读、搜索、笔记、图表始终离线可用，不需要任何模型通道；
            只有翻译、要点总结与问答需要模型。
          </p>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function Step({
  index,
  title,
  detail,
  state,
  children,
}: {
  index: number;
  title: string;
  detail: string;
  state: "done" | "todo" | "wait";
  children?: React.ReactNode;
}) {
  const badge = state === "done" ? "chip-ok" : state === "todo" ? "chip-warn" : "";
  const label = state === "done" ? "已完成" : state === "todo" ? "待完成" : "等待前置步骤";
  return (
    <li className="rounded-xl border border-line bg-paper-2/60 p-3">
      <div className="flex items-center gap-2">
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent text-[11px] font-semibold">
          {index}
        </span>
        <span className="font-medium">{title}</span>
        <span className={`chip ${badge}`}>{label}</span>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-ink-2">{detail}</p>
      {children}
    </li>
  );
}
