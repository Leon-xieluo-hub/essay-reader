import { UploadDropzone } from "../components/UploadDropzone";
import { navigate } from "../hooks/useHashRoute";
import { useT } from "../i18n";
import { qualityScore, useApp } from "../store";

export function Library() {
  const t = useT();
  const documents = useApp((s) => s.documents);
  const providers = useApp((s) => s.providers);
  const environment = useApp((s) => s.environment);
  const removeDocument = useApp((s) => s.removeDocument);

  const local = providers.find((p) => p.name === "local");
  const cloud = providers.find((p) => p.name === "cloud");

  return (
    <div className="h-full overflow-y-auto px-6 py-8">
      <div className="mx-auto max-w-4xl">
        <header className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">Essay Reader</h1>
          <p className="mt-1 text-sm leading-relaxed text-ink-2">
            {t("文献阅读器 · 精准解析 PDF、双通道翻译（本地免费离线 / 云端更准）、结构化要点与带出处的问答。 所有文件与译文都留在本机。")}
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
            <span className="chip chip-ok">{t("解析 / 阅读 / 笔记：完全离线")}</span>
            <span className={`chip ${local?.available ? "chip-ok" : "chip-warn"}`}>
              {t("本地翻译：{state}", { state: local?.available ? t("可用（零 token）") : t("需下载模型") })}
            </span>
            <span className={`chip ${cloud?.available ? "chip-ok" : "chip-warn"}`}>
              {t("云端翻译：{state}", { state: cloud?.available ? t("可用（按量计费）") : t("未配置") })}
            </span>
            <span className={`chip ${environment?.internet ? "" : "chip-warn"}`}>
              {t("网络：{state}", { state: environment?.internet ? t("已连接") : t("离线") })}
            </span>
          </div>
        </header>

        <UploadDropzone />

        <section className="mt-8">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold">{t("文献库（{count}）", { count: documents.length })}</h2>
            {documents.length > 0 && (
              <span className="text-[11px] text-ink-3">{t("点击卡片开始阅读")}</span>
            )}
          </div>

          {documents.length === 0 ? (
            <p className="rounded-xl border border-dashed border-line-2 p-8 text-center text-sm text-ink-3">
              {t("上传第一篇文献后，这里会显示解析质量、图表数量与阅读入口。")}
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {documents.map((item) => {
                const report = item.parse_report;
                const score = report ? Math.round(qualityScore(report)) : null;
                return (
                  <article key={item.id} className="card flex flex-col p-3">
                    <button className="text-left" onClick={() => navigate(`#/doc/${item.id}`)}>
                      <h3 className="line-clamp-2 text-sm font-medium leading-snug">
                        {item.title || item.filename}
                      </h3>
                      <p className="mt-1 text-[11px] text-ink-3">
                        {t("{count} 页", { count: item.page_count })} · {(item.file_size / 1024 / 1024).toFixed(1)} MB ·{" "}
                        {new Date(item.created_at).toLocaleDateString()}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-1 text-[10.5px]">
                        {report && (
                          <>
                            <span className="chip">
                              {report.alignment === "double" ? t("双栏") : report.alignment === "single" ? t("单栏") : t("混排")}
                            </span>
                            <span className="chip">{t("段落 {count}", { count: report.paragraph_count })}</span>
                            {report.figure_count > 0 && <span className="chip">{t("图 {count}", { count: report.figure_count })}</span>}
                            {report.table_count > 0 && <span className="chip">{t("表 {count}", { count: report.table_count })}</span>}
                            <span
                              className={`chip ${score !== null && score >= 80 ? "chip-ok" : score !== null && score >= 55 ? "chip-warn" : "chip-danger"}`}
                            >
                              {t("解析质量 {score}", { score: score ?? "" })}
                            </span>
                          </>
                        )}
                      </div>
                    </button>
                    <div className="mt-3 flex justify-end gap-1">
                      <a className="btn !text-[11px]" href={`/api/documents/${item.id}/file`} target="_blank" rel="noreferrer">
                        {t("原始 PDF")}
                      </a>
                      <button
                        className="btn !text-[11px] text-danger"
                        onClick={() => {
                          if (confirm(t("删除《{name}》及其译文与笔记？", { name: item.title || item.filename }))) {
                            void removeDocument(item.id);
                          }
                        }}
                      >
                        {t("删除")}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
