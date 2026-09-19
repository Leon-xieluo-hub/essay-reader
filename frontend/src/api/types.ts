// Wire types — mirror backend/app/schemas.py exactly.

export type BlockType =
  | "heading"
  | "text"
  | "figure"
  | "table"
  | "formula"
  | "reference"
  | "footnote"
  | "caption"
  | "meta"
  | "header"
  | "footer";

export type ProviderKey = "local" | "cloud" | "off";

export interface BBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface PageInfo {
  index: number;
  width: number;
  height: number;
  rotation: number;
  block_count: number;
}

export interface ParseReport {
  text_coverage: number;
  garbage_ratio: number;
  table_count: number;
  figure_count: number;
  formula_count: number;
  paragraph_count: number;
  alignment: "single" | "double" | "mixed" | "unknown";
  channel: string;
  ocr_pages: number;
  ocr_confidence: number;
  warnings: string[];
  duration_ms: number;
}

export interface DocumentMeta {
  id: string;
  filename: string;
  title: string;
  authors: string[];
  page_count: number;
  file_size: number;
  sha256: string;
  created_at: string;
  status: string;
  parse_report: ParseReport | null;
}

export interface DocumentDetail extends DocumentMeta {
  pages: PageInfo[];
}

export interface TranslationMeta {
  provider: string;
  model: string;
  lang: string;
  quality: "ok" | "suspect" | "failed" | "manual";
  attempts: number;
}

export interface DocBlock {
  id: string;
  order: number;
  page: number;
  type: BlockType;
  text: string;
  bbox: BBox;
  column: number;
  level: number | null;
  size: number;
  image_url: string | null;
  latex: string | null;
  caption: string | null;
  table_html: string | null;
  table_rows: string[][] | null;
  table_rows_translated: string[][] | null;
  flags: string[];
  translations: Record<string, string>;
  translation_meta: Record<string, TranslationMeta>;
  note_count: number;
}

export interface ProviderStatus {
  name: string;
  available: boolean;
  detail: string;
  model: string;
  base_url: string;
  is_local: boolean;
  installed_models: string[];
}

export interface TaskState {
  id: string;
  doc_id: string;
  kind: string;
  provider: string;
  status: "running" | "done" | "error" | "cancelled";
  total: number;
  done: number;
  message: string;
  error: string;
  started_at: string;
  finished_at: string;
}

export interface Note {
  id: number;
  doc_id: string;
  block_id: string;
  quote: string;
  comment: string;
  color: string;
  created_at: string;
}

export interface GlossaryTerm {
  id: number;
  doc_id: string;
  source: string;
  target: string;
  note: string;
  locked: boolean;
}

export interface UsageStats {
  cloud_tokens_in: number;
  cloud_tokens_out: number;
  cloud_estimated_cost_cny: number;
  local_blocks_translated: number;
  local_seconds: number;
}

export interface SettingsDict {
  llm_provider: ProviderKey;
  local_base_url: string;
  local_model: string;
  cloud_base_url: string;
  cloud_model: string;
  cloud_api_key_set: boolean;
  local_concurrency: number;
  cloud_concurrency: number;
  chunk_token_budget: number;
  context_paragraphs: number;
  token_budget_per_doc: number;
  request_timeout_s: number;
  max_retries: number;
  quality_retry_limit: number;
  cloud_price_in: number;
  cloud_price_out: number;
  render_dpi: number;
  ocr_enabled: boolean;
  ocr_mode: "auto" | "force" | "off";
  ocr_dpi: number;
  ocr_min_text_chars: number;
}

export type OcrMode = "auto" | "force" | "off";

export interface EnvironmentInfo {
  internet: boolean;
  provider: ProviderKey;
  offline_capable: boolean;
  ocr: { available: boolean; detail: string; mode: OcrMode };
  configured: SettingsDict;
}

export interface TranslateEstimate {
  blocks: number;
  chunks: number;
  estimated_tokens_in: number;
  estimated_tokens_out: number;
  estimated_cost_cny: number;
  local_eta_seconds: number;
}

export interface AskEvidence {
  block_id: string;
  page: number;
  quote: string;
}

/** Diagnostics + actionable next steps for getting an AI channel working. */
export interface SetupGuide {
  platform: string;
  local: {
    available: boolean;
    detail: string;
    model: string;
    base_url: string;
    binary_found: boolean;
    binary_path: string;
    installed_models: string[];
    needs: "ready" | "install_runtime" | "pull_model";
  };
  cloud: {
    available: boolean;
    detail: string;
    model: string;
    base_url: string;
    api_key_set: boolean;
  };
  links: Record<string, string>;
  commands: Record<string, string>;
}

export interface AskAnswer {
  answer: string;
  evidence: AskEvidence[];
  grounded: boolean;
  provider: string;
  model: string;
}
