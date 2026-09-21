import { PdfPane } from "../components/PdfPane";
import { ReadingPane } from "../components/ReadingPane";
import { Dock } from "../components/TranslationDock";
import { useT } from "../i18n";
import { useApp } from "../store";

export function DocumentView() {
  const mode = useApp((s) => s.mode);
  const doc = useApp((s) => s.doc);
  const environment = useApp((s) => s.environment);
  const provider = useApp((s) => s.provider);
  const providers = useApp((s) => s.providers);
  const loading = useApp((s) => s.loadingDoc);

  const local = providers.find((p) => p.name === "local");
  const cloud = providers.find((p) => p.name === "cloud");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <StatusStrip
        offline={environment ? !environment.internet : false}
        provider={provider}
        localReady={Boolean(local?.available)}
        cloudReady={Boolean(cloud?.available)}
        warning={doc?.parse_report?.warnings?.[0]}
      />
      {loading ? (
        <div className="flex-1 p-8">
          <div className="mx-auto max-w-[74ch] space-y-3">
            {Array.from({ length: 8 }, (_, index) => (
              <div key={index} className="skeleton h-4" style={{ width: `${70 + ((index * 7) % 30)}%` }} />
            ))}
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          <div className="min-w-0 flex-1">{mode === "pdf" ? <PdfPane /> : <ReadingPane />}</div>
          <Dock />
        </div>
      )}
    </div>
  );
}

function StatusStrip({
  offline,
  provider,
  localReady,
  cloudReady,
  warning,
}: {
  offline: boolean;
  provider: string;
  localReady: boolean;
  cloudReady: boolean;
  warning?: string;
}) {
  const t = useT();
  const messages: { kind: string; text: string }[] = [];

  if (offline) {
    messages.push({
      kind: "chip-warn",
      text: t("当前离线 · 解析、阅读、笔记照常可用；本地模型翻译不受影响，云端入口已置灰"),
    });
  }
  if (provider === "off") {
    messages.push({
      kind: "chip",
      text: t("纯阅读模式（零 token、零网络）：需要翻译或总结时，请在顶栏切换模型通道"),
    });
  } else if (provider === "local") {
    messages.push({
      kind: "chip-ok",
      text: localReady
        ? t("本地模型 · 免费离线，长难句与术语建议复核（可疑段落会被标出）")
        : t("本地模型未就绪：请在设置中下载模型，或切到云端通道"),
    });
  } else if (provider === "cloud") {
    messages.push({
      kind: cloudReady ? "chip-warn" : "chip-danger",
      text: cloudReady
        ? t("云端模型 · 更准确，按 token 计费（翻译前会给出预估）")
        : t("云端通道不可用：检查 API Key 与网络，或切回本地通道"),
    });
  }
  if (warning) messages.push({ kind: "chip-warn", text: warning });

  if (!messages.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line bg-paper-3/50 px-3 py-1.5 text-[11px]">
      {messages.map((message) => (
        <span key={message.text} className={`chip ${message.kind}`}>
          {message.text}
        </span>
      ))}
    </div>
  );
}
