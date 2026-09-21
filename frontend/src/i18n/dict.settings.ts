/** Settings panel strings. */
export const SETTINGS_DICT: Record<string, string> = {
  // Shell / local model pull
  "设置": "Settings",
  "关闭": "Close",
  "请先填写模型名称，例如 qwen3:8b": "Enter a model name first, for example qwen3:8b",
  "连接本地推理服务…": "Connecting to the local inference service…",
  "下载失败：{error}": "Download failed: {error}",
  "下载中": "Downloading",
  "完成": "Done",

  // Model channels
  "模型通道": "Model channels",
  "本地=免费离线；云端=更准但按 token 计费。两种通道可随时切换，术语表与已翻译段落共用。":
    "Local = free and offline; cloud = more accurate but billed per token. Switch anytime — the glossary and translated paragraphs are shared.",
  "本地模型（Ollama）": "Local model (Ollama)",
  "云端模型（OpenAI 兼容）": "Cloud model (OpenAI-compatible)",
  "检测中…": "Checking…",
  "端点 {url}": "Endpoint {url}",
  "当前模型 {model}": "Current model {model}",
  "可用": "Available",
  "不可用": "Unavailable",

  // Local model management
  "本地模型管理": "Local model management",
  "首次使用需要一次性联网下载模型权重（约 4~5GB）；下载完成后即可全程离线使用。":
    "First use needs a one-time online download of the model weights (about 4–5GB); after that it runs fully offline.",
  "推理服务端点": "Inference service endpoint",
  "模型名称": "Model name",
  "下载 / 更新此模型": "Download / update this model",
  "刷新已安装列表": "Refresh installed models",
  "已安装：{models}": "Installed: {models}",
  "未检测到已安装模型": "No installed models detected",
  "无外网环境？离线导入模型包": "No internet? Import the model package offline",
  "在能联网的机器上执行": "On a machine with internet access, run",
  "，把 Ollama 的模型目录（Windows:": ", then copy Ollama's model directory (Windows:",
  "）整体拷贝到本机同一路径，然后重启本地推理服务即可，全程无需联网。":
    ") to the same path on this machine and restart the local inference service. No internet needed at any point.",

  // OCR
  "扫描件 OCR（本地离线）": "Scanned-page OCR (local, offline)",
  "没有文本层的扫描 PDF 需要 OCR 才能阅读与翻译。RapidOCR 在 CPU 上运行，完全离线，约 1~3 秒/页；它不会与本地模型抢显存。":
    "Scanned PDFs without a text layer need OCR before they can be read or translated. RapidOCR runs on the CPU, fully offline, at about 1–3 seconds per page; it does not compete with the local model for VRAM.",
  "OCR 引擎就绪": "OCR engine ready",
  "OCR 不可用": "OCR unavailable",
  "处理方式": "Processing mode",
  "自动：仅对扫描页做 OCR（推荐）": "Auto: OCR scanned pages only (recommended)",
  "强制：所有页面都过 OCR": "Force: OCR every page",
  "关闭：只用文本层": "Off: text layer only",
  "切换后立即生效，下次上传生效。OCR 结果会在解析质量里标注处理页数与置信度，":
    "Takes effect immediately and applies to the next upload. OCR results note the processed page count and confidence in the parse quality,",
  "并在质量分中体现不确定性 —— 建议对照「原版页」核对关键数字。":
    "and factor that uncertainty into the quality score — check key numbers against “Original page”.",

  // Cloud API
  "云端 API（可选）": "Cloud API (optional)",
  "密钥只保存在本机后端，不会写入前端或仓库，界面仅显示是否已配置。":
    "The key is stored only in the local backend, never in the frontend or the repository; the UI only shows whether it is set.",
  "模型": "Model",
  "已配置": "Configured",
  "留空表示不修改": "Leave blank to keep unchanged",

  // Translation and quality
  "翻译与质量": "Translation and quality",
  "本地通道并发固定为 1（显存约束），并且必须开启质量校验——本地模型在数字与引用上更容易出错。":
    "The local channel is fixed at concurrency 1 (VRAM limit) and quality checks are always on — local models are more error-prone with numbers and citations.",
  "分块 token 上限": "Chunk token limit",
  "本地模型建议 800~1200": "800–1200 recommended for local models",
  "上下文段落数": "Context paragraphs",
  "用于减少指代错误": "Reduces reference errors",
  "质量重译次数": "Quality retries",
  "本地并发": "Local concurrency",
  "显存不足时保持 1": "Keep at 1 if VRAM is low",
  "云端并发": "Cloud concurrency",
  "单篇 token 预算": "Token budget per document",
  "0 表示不限制": "0 means no limit",

  // Usage
  "用量与费用": "Usage and cost",
  "云端按 token 计费；本地只统计处理量与耗时。":
    "Cloud is billed per token; local only tracks volume and time.",
  "云端输入 token": "Cloud input tokens",
  "云端输出 token": "Cloud output tokens",
  "预估费用": "Estimated cost",
  "本地处理段落": "Local paragraphs processed",
  "清零统计": "Reset stats",

  // Reading and appearance
  "阅读与外观": "Reading and appearance",
  "主题": "Theme",
  "跟随系统": "Follow system",
  "米白浅色": "Warm light",
  "夜间": "Dark",
  "字号 {percent}%": "Font size {percent}%",

  // Offline status
  "离线状态": "Offline status",
  "网络：已连接": "Network: connected",
  "网络：离线": "Network: offline",
  "解析 / 阅读 / 笔记：始终离线可用": "Parsing / reading / notes: always available offline",
  "本地翻译：可用（零 token）": "Local translation: available (zero tokens)",
  "本地翻译：需先下载模型": "Local translation: download a model first",
  "云端翻译：可用（按量计费）": "Cloud translation: available (metered)",
  "云端翻译：不可用": "Cloud translation: unavailable",
  "本软件不上报任何使用数据；除首次下载模型权重与可选的云端调用外，运行期不发任何外部请求。":
    "This app reports no usage data; apart from the first model download and optional cloud calls, it makes no external requests at runtime.",

  // Save
  "保存设置": "Save settings",
};
