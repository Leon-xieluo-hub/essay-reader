/** Library, document view, upload, PDF pane, lightbox, toasts, api client. */
export const VIEWS_DICT: Record<string, string> = {
  // Library
  "文献阅读器 · 精准解析 PDF、双通道翻译（本地免费离线 / 云端更准）、结构化要点与带出处的问答。 所有文件与译文都留在本机。":
    "Essay Reader · precise PDF parsing, dual-channel translation (free and offline locally / more accurate in the cloud), structured summaries and grounded Q&A. Papers and translations never leave your machine.",
  "解析 / 阅读 / 笔记：完全离线": "Parsing / reading / notes: fully offline",
  "本地翻译：{state}": "Local translation: {state}",
  "可用（零 token）": "Available (zero tokens)",
  "需下载模型": "Download a model first",
  "云端翻译：{state}": "Cloud translation: {state}",
  "可用（按量计费）": "Available (pay per use)",
  "未配置": "Not configured",
  "网络：{state}": "Network: {state}",
  已连接: "Connected",
  离线: "Offline",
  "文献库（{count}）": "Library ({count})",
  点击卡片开始阅读: "Pick a card to start reading",
  "上传第一篇文献后，这里会显示解析质量、图表数量与阅读入口。":
    "Upload your first paper and this list will show parse quality, figure counts and a way in.",
  "{count} 页": "{count} pages",
  双栏: "two-column",
  单栏: "single-column",
  混排: "mixed",
  "段落 {count}": "{count} paragraphs",
  "图 {count}": "{count} figures",
  "表 {count}": "{count} tables",
  "解析质量 {score}": "Parse quality {score}",
  "原始 PDF": "Original PDF",
  "删除《{name}》及其译文与笔记？": "Delete “{name}” with its translations and notes?",
  删除: "Delete",

  // Document view status strip
  "当前离线 · 解析、阅读、笔记照常可用；本地模型翻译不受影响，云端入口已置灰":
    "Currently offline · parsing, reading and notes still work; local translation is unaffected and the cloud option is greyed out",
  "纯阅读模式（零 token、零网络）：需要翻译或总结时，请在顶栏切换模型通道":
    "Reading-only mode (zero tokens, no network): switch the model channel in the top bar when you need translation or summaries",
  "本地模型 · 免费离线，长难句与术语建议复核（可疑段落会被标出）":
    "Local model · free and offline; review long sentences and terms (suspect paragraphs are flagged)",
  "本地模型未就绪：请在设置中下载模型，或切到云端通道":
    "Local model not ready: download a model in Settings, or switch to the cloud channel",
  "云端模型 · 更准确，按 token 计费（翻译前会给出预估）":
    "Cloud model · more accurate, billed per token (an estimate is shown before translating)",
  "云端通道不可用：检查 API Key 与网络，或切回本地通道":
    "Cloud channel unavailable: check the API key and your network, or switch back to local",

  // Upload
  "扫描件（没有文本层）需要 OCR；文本层 PDF 会自动跳过 OCR":
    "Scanned files (no text layer) need OCR; text-layer PDFs skip OCR automatically",
  // The English value carries the leading space the Chinese parenthesis does not need.
  "扫描件 OCR{state}": "OCR for scanned files{state}",
  "（本地离线）": " (local, offline)",
  "（引擎不可用）": " (engine unavailable)",
  "只支持 PDF 文件": "Only PDF files are supported",
  "上传中 {percent}%": "Uploading {percent}%",
  "解析中（扫描件 OCR 约 1~3 秒/页）…": "Parsing (OCR takes about 1~3 seconds per page on scans)…",
  "＋ 上传 PDF": "＋ Upload PDF",
  "拖入 PDF，或点击选择文件": "Drop in a PDF, or click to choose a file",
  "本地解析：双栏、图表、公式都会保留；不会上传到任何服务器":
    "Parsed locally: columns, figures and formulas are all kept; nothing is uploaded to any server",

  // PDF pane
  "PDF 渲染失败：{reason}": "PDF rendering failed: {reason}",
  "正在加载原始 PDF…": "Loading the original PDF…",
  "原版页模式：按真实排版渲染，选中段落会在页面上高亮对应区域 —— 这是核对解析与图表位置的最可靠方式。":
    "Original page mode: rendered with the real layout, and the selected paragraph is highlighted where it sits on the page — the most reliable way to check parsing and figure placement.",

  // Lightbox
  "原图裁切（解析器按 bbox 保留，可与正文对照）":
    "Original crop (kept by the parser as a bbox, so it can be compared with the body text)",
  "关闭 (Esc)": "Close (Esc)",

  // API client
  "上传失败（{status}）": "Upload failed ({status})",
  "网络错误：无法连接到本地服务": "Network error: cannot reach the local service",
};
