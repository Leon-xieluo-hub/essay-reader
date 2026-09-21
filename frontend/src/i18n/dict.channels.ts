/** Channel picker, translation dock, setup guide. */
export const CHANNEL_DICT: Record<string, string> = {
  // Dock tabs
  要点: "Summary",
  问答: "Q&A",
  笔记: "Notes",
  术语表: "Glossary",
  解析质量: "Parse quality",
  展开侧面板: "Expand side panel",
  收起: "Collapse",

  // Summary tab
  "生成中…": "Generating…",
  重新生成要点: "Regenerate summary",
  生成结构化要点: "Generate structured summary",
  "云端 · 按 token 计费": "Cloud · billed per token",
  "本地 · 免费离线": "Local · free, offline",
  "AI 功能已关闭（纯阅读模式）。在顶栏的通道菜单或设置里启用本地/云端模型后即可生成要点。":
    "AI features are off (reading-only mode). Enable a local or cloud model from the channel menu in the top bar or from settings to generate summaries.",
  "生成后会得到：研究问题 / 方法与技术路线 / 数据与实验设置 / 主要结论 / 创新点 / 局限 / 关键数据 / 可复用之处， 每个结论尽量带具体数字。可导出为 Markdown。":
    "You'll get: research question / methods and technical route / data and experiment setup / main conclusions / contributions / limitations / key numbers / reusable ideas, with concrete figures wherever possible. Exportable as Markdown.",

  // Chat tab
  "基于本文内容作答，并给出处（段落 + 页码）；文中没有依据时会明确说明「文中未提及」。 点击任意段落后再提问，会优先以该段落为依据。":
    "Answers are based on this paper and come with sources (paragraph + page); when there is no support in the text it says “not mentioned in the text”. Select a paragraph before asking to ground the answer in it.",
  我: "Me",
  助手: "Assistant",
  文中未提及: "Not mentioned in the text",
  "第 {page} 页": "Page {page}",
  优先依据当前选中段落: "Ground the answer in the selected paragraph",
  先在正文中点选一段可限定依据: "Select a paragraph in the text to narrow the sources",
  "例如：这篇论文的核心创新点是什么？": "e.g. What is the main contribution of this paper?",
  "AI 已关闭": "AI is off",
  "本地模型 · 免费离线": "Local model · free, offline",
  "云端模型 · 按量计费": "Cloud model · pay as you go",
  清空: "Clear",
  提问: "Ask",

  // Notes tab
  "共 {count} 条（保存在本地）": "{count} notes (stored locally)",
  导出含笔记: "Export with notes",
  "悬停任意段落点击「笔记」即可添加批注；笔记会随 Markdown 一起导出。":
    "Hover any paragraph and click “Notes” to add a comment; notes are exported together with the Markdown.",
  跳到该段落: "Jump to paragraph",
  删除: "Delete",

  // Glossary tab
  "术语表决定全文译法一致性，翻译时会强制注入。修改后对新翻译立即生效，也可对个别段落点「重译」。":
    "The glossary keeps terminology consistent across the whole paper and is always injected when translating. Changes apply to new translations immediately; you can also re-translate individual paragraphs.",
  "抽取中…": "Extracting…",
  自动抽取术语: "Auto-extract terms",
  "{count} 条": "{count} terms",
  原文术语: "Source term",
  译法: "Translation",
  添加: "Add",
  手动: "Manual",
  暂无术语: "No terms yet",

  // Quality tab
  "解析质量与翻译质量都如实呈现：不确定的地方宁可标出来，也不假装完美。":
    "Parse and translation quality are reported as they are: uncertain spots are flagged rather than glossed over.",
  解析自检: "Parse self-check",
  版面判定: "Layout detection",
  段落数: "Paragraphs",
  "图表 / 表格 / 公式": "Figures / tables / formulas",
  文本覆盖率: "Text coverage",
  乱码率: "Garbled ratio",
  解析耗时: "Parse time",
  "OCR 处理页数": "OCR pages",
  "OCR 平均置信度": "Average OCR confidence",
  "{count} 页": "{count} pages",
  "OCR 结果是识别重建，标点、连字符与个别字符可能与原页面不一致， 关键数字请对照「原版页」核对。":
    "OCR is a reconstructed reading: punctuation, hyphens and individual characters may differ from the original page. Check key numbers against “Original page”.",
  "翻译质量（当前通道：{channel}）": "Translation quality (current channel: {channel})",
  已翻译段落: "Translated paragraphs",
  正常: "OK",
  "待复核（校验未通过）": "Needs review (validation failed)",
  失败: "Failed",
  "可疑段落已在正文左侧以黄色标记。「待复核」通常意味着数字、引用或占位符数量与原文不一致， 建议对照「原版页」核对，或用云端通道重译该段。":
    "Suspicious paragraphs are marked in yellow on the left of the text. “Needs review” usually means the number of digits, citations or placeholders differs from the source; check it against “Original page” or re-translate that paragraph with a cloud channel.",
  双栏: "two-column",
  单栏: "single-column",
  混排: "mixed",
  未知: "Unknown",
  "OCR 识别": "OCR",
  "文本层 + OCR": "Text layer + OCR",
  文本层: "Text layer",

  // Setup guide — progress captions
  "请填写要下载的模型名，例如 qwen3:8b": "Enter the model to download, e.g. qwen3:8b",
  "正在连接本地推理服务并下载 {model}…":
    "Connecting to the local inference service and downloading {model}…",
  "下载失败：{error}": "Download failed: {error}",
  下载中: "Downloading",
  "下载流程结束，可点击「重新检测」确认": "Download finished — click “Check again” to confirm",
  "正在下载安装包…": "Downloading the installer…",
  "已保存到 {path}（{size} MB）": "Saved to {path} ({size} MB)",

  // Setup guide — local channel
  启用云端模型: "Enable a cloud model",
  启用本地模型: "Enable a local model",
  "翻译、要点与问答需要一条可用的模型通道。下面按依赖顺序给出每一步，完成后可随时回来点「重新检测」。":
    "Translation, summaries and Q&A need a working model channel. The steps below are in dependency order; you can come back and click “Check again” at any time.",
  关闭: "Close",
  "正在检测环境…": "Checking the environment…",
  "安装本地推理引擎（Ollama）": "Install the local inference engine (Ollama)",
  "已检测到：{path}": "Detected: {path}",
  "尚未检测到 Ollama。可以一键下载官方安装包，或自行从官网下载。":
    "Ollama was not detected. Use the one-click installer below, or download it from the official site.",
  "下载中…": "Downloading…",
  一键下载安装包: "Download installer",
  打开官网下载页: "Open the download page",
  "下载完成后双击安装；静默安装可用":
    "Double-click to install after the download; a silent install also works",
  启动推理服务: "Start the inference service",
  "安装完成后 Ollama 会常驻后台（托盘图标）。若未启动，运行 `ollama serve`。":
    "After installing, Ollama stays in the background (tray icon). If it is not running, run `ollama serve`.",
  "当前端点：": "Current endpoint:",
  下载翻译模型: "Download a translation model",
  "已安装 {count} 个模型：{models}": "{count} models installed: {models}",
  "模型权重在应用内下载，全程离线可用；8GB 显存建议 8B 级 Q5/Q6 量化。":
    "Weights are downloaded inside the app and work fully offline; with 8GB of VRAM an 8B-class Q5/Q6 quantization is recommended.",
  一键下载模型: "Download model",
  浏览模型库: "Browse the model library",
  "命令行方式：": "From the command line:",
  切换通道并开始翻译: "Switch channel and start translating",
  "本地通道已就绪：免费、离线、数据不出本机。":
    "The local channel is ready: free, offline, data never leaves this machine.",
  "三步完成后，本通道会变为可用。": "This channel becomes available once the three steps above are done.",
  重新检测: "Check again",
  切换到本地模型: "Switch to the local model",

  // Setup guide — cloud channel
  "云端通道兼容任何 OpenAI 格式接口（DeepSeek、OpenAI、自建中转均可）。密钥只保存在本机后端，界面不会回显，也不会写入仓库。":
    "The cloud channel works with any OpenAI-compatible API (DeepSeek, OpenAI or your own relay). The key is stored only in the local backend; it is never echoed in the UI and never written to the repository.",
  已配置: "Configured",
  保存并检测: "Save and check",
  "获取 DeepSeek Key": "Get a DeepSeek key",
  接口文档: "API docs",
  "当前模型：": "Current model:",
  已保存密钥: "key saved",
  尚未保存密钥: "no key saved yet",
  "提示：解析、阅读、搜索、笔记、图表始终离线可用，不需要任何模型通道；只有翻译、要点总结与问答需要模型。":
    "Note: parsing, reading, search, notes and figures always work offline and need no model channel; only translation, summaries and Q&A need a model.",

  // Setup guide — step states
  已完成: "Done",
  待完成: "To do",
  等待前置步骤: "Waiting for earlier steps",

  // Top bar — channel chip and menu
  "本地 · {model}": "Local · {model}",
  "云端 · {model}": "Cloud · {model}",
  未配置: "Not configured",
  "选择模型通道": "Choose a model channel",
  "如何启用？": "How to enable?",
  "模型通道 · 场景分工": "Model channel · role split",
  本地模型: "Local model",
  云端模型: "Cloud model",
  "关闭 AI（纯阅读）": "Turn AI off (reading only)",
  "免费 · 离线 · 数据不出本机": "Free · offline · data never leaves this machine",
  "更准确 · 按 token 计费": "More accurate · billed per token",
  "零 token · 零网络": "Zero tokens · zero network",
  "只解析与阅读，翻译/总结/问答入口置灰": "Parsing and reading only; translate / summary / Q&A are disabled",
  // 检测中… already lives in dict.settings.ts
  "长难句与专业术语建议人工复核，界面会标出可疑段落":
    "Long or complex sentences and technical terms are worth a human check; suspicious paragraphs are flagged in the UI",
  "翻译前会给出预计 token 与费用；不可用时可切回本地":
    "Estimated tokens and cost are shown before translating; if it is unavailable you can switch back to local",
  环境搭建引导: "Setup guide",
  打开设置: "Open settings",
  可用: "Available",
  不可用: "Unavailable",
  "查看启用步骤（下载 / 部署引导）": "See setup steps (download / deploy)",

  // Top bar — translate button
  "AI 功能已关闭，请在通道菜单中启用": "AI features are off — enable a channel from the channel menu",
  "当前通道不可用：点击查看启用步骤": "This channel is unavailable: click to see the setup steps",
  "本地模型：免费离线，预计约 {minutes} 分钟": "Local model: free and offline, about {minutes} min",
  "云端：预计 {tokens} token ≈ ¥{cost}": "Cloud: about {tokens} tokens ≈ ¥{cost}",
  "本地模型翻译：免费、离线": "Local model translation: free, offline",
  "云端翻译：更快更准，按 token 计费": "Cloud translation: faster and more accurate, billed per token",
  "翻译中 {done}/{total}": "Translating {done}/{total}",
  翻译全文: "Translate all",
  启用通道: "Enable channel",

  // Top bar — progress line channel chip
  本地: "Local",
  云端: "Cloud",
};
