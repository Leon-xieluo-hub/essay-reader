import type {
  AskAnswer,
  DocBlock,
  DocumentDetail,
  DocumentMeta,
  EnvironmentInfo,
  GlossaryTerm,
  Note,
  ProviderKey,
  ProviderStatus,
  SettingsDict,
  SetupGuide,
  TaskState,
  TranslateEstimate,
  UsageStats,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string; data_dir: string }>("/api/health"),

  environment: () => request<EnvironmentInfo>("/api/environment"),

  providers: () => request<ProviderStatus[]>("/api/providers"),

  listDocuments: () => request<DocumentMeta[]>("/api/documents"),

  getDocument: (docId: string) => request<DocumentDetail>(`/api/documents/${docId}`),

  deleteDocument: (docId: string) =>
    request<{ ok: boolean }>(`/api/documents/${docId}`, { method: "DELETE" }),

  getBlocks: (docId: string, lang: string) =>
    request<DocBlock[]>(`/api/documents/${docId}/blocks?lang=${encodeURIComponent(lang)}`),

  uploadDocument: (file: File, ocr: string, onProgress?: (percent: number) => void) =>
    new Promise<DocumentDetail>((resolve, reject) => {
      const form = new FormData();
      form.append("file", file);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/documents?ocr=${encodeURIComponent(ocr)}`);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText) as DocumentDetail);
        } else {
          let detail = `上传失败（${xhr.status}）`;
          try {
            const body = JSON.parse(xhr.responseText);
            if (body?.detail) detail = body.detail;
          } catch {
            /* ignore */
          }
          reject(new Error(detail));
        }
      };
      xhr.onerror = () => reject(new Error("网络错误：无法连接到本地服务"));
      xhr.send(form);
    }),

  pdfUrl: (docId: string) => `/api/documents/${docId}/file`,

  exportUrl: (docId: string, lang: string, mode: string) =>
    `/api/documents/${docId}/export?lang=${lang}&mode=${mode}`,

  translate: (payload: {
    doc_id: string;
    provider: ProviderKey;
    lang: string;
    style: string;
    block_ids?: string[];
    force?: boolean;
  }) => request<TaskState>("/api/translate", { method: "POST", body: JSON.stringify(payload) }),

  estimate: (payload: { doc_id: string; provider: ProviderKey; lang: string; style: string }) =>
    request<TranslateEstimate>("/api/translate/estimate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  task: (taskId: string) => request<TaskState>(`/api/tasks/${taskId}`),

  summary: (docId: string, lang: string) =>
    request<{ content: string; provider: string; model: string }>(
      `/api/summary/${docId}?lang=${encodeURIComponent(lang)}`,
    ),

  createSummary: (payload: {
    doc_id: string;
    provider: ProviderKey;
    lang: string;
    force?: boolean;
  }) => request<TaskState>("/api/summary", { method: "POST", body: JSON.stringify(payload) }),

  ask: (payload: {
    doc_id: string;
    question: string;
    provider: ProviderKey;
    lang: string;
    block_ids?: string[];
  }) => request<AskAnswer>("/api/ask", { method: "POST", body: JSON.stringify(payload) }),

  notes: (docId: string) => request<Note[]>(`/api/notes/${docId}`),

  addNote: (payload: { doc_id: string; block_id: string; quote: string; comment: string; color?: string }) =>
    request<Note>("/api/notes", { method: "POST", body: JSON.stringify(payload) }),

  deleteNote: (noteId: number) => request<{ ok: boolean }>(`/api/notes/${noteId}`, { method: "DELETE" }),

  glossary: (docId: string) => request<GlossaryTerm[]>(`/api/glossary/${docId}`),

  saveTerm: (docId: string, payload: { source: string; target: string; note?: string }) =>
    request<GlossaryTerm[]>(`/api/glossary?doc_id=${encodeURIComponent(docId)}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  deleteTerm: (docId: string, termId: number) =>
    request<{ ok: boolean }>(`/api/glossary/${docId}/${termId}`, { method: "DELETE" }),

  buildGlossary: (docId: string, provider: ProviderKey, lang: string) =>
    request<{ terms: GlossaryTerm[] }>(
      `/api/glossary/${docId}/build?provider=${provider}&lang=${lang}`,
      { method: "POST" },
    ),

  settings: () => request<SettingsDict>("/api/settings"),

  saveSettings: (payload: Partial<SettingsDict> & { cloud_api_key?: string }) =>
    request<{ changed: string[]; settings: SettingsDict }>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  usage: () => request<UsageStats>("/api/usage"),

  resetUsage: () => request<{ ok: boolean }>("/api/usage/reset", { method: "POST" }),

  models: () => request<{ installed: string[]; current: string }>("/api/models"),

  setupGuide: () => request<SetupGuide>("/api/setup/guide"),

  /** Download the Ollama installer with progress (Server-Sent Events). */
  downloadOllama: (
    url: string,
    onEvent: (event: Record<string, unknown>) => void,
    onDone: () => void,
  ) => {
    fetch("/api/setup/download-ollama", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    })
      .then(async (response) => {
        const reader = response.body?.getReader();
        if (!reader) return;
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() ?? "";
          for (const part of parts) {
            const line = part.replace(/^data:\s*/, "").trim();
            if (!line) continue;
            try {
              onEvent(JSON.parse(line) as Record<string, unknown>);
            } catch {
              /* ignore malformed chunk */
            }
          }
        }
      })
      .finally(onDone);
  },

  /** Streams Ollama pull progress as Server-Sent Events. */
  pullModel: (
    model: string,
    onEvent: (event: Record<string, unknown>) => void,
    onDone: () => void,
  ) => {
    fetch("/api/models/pull", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    })
      .then(async (response) => {
        const reader = response.body?.getReader();
        if (!reader) return;
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() ?? "";
          for (const part of parts) {
            const line = part.replace(/^data:\s*/, "").trim();
            if (!line) continue;
            try {
              onEvent(JSON.parse(line) as Record<string, unknown>);
            } catch {
              /* ignore malformed chunk */
            }
          }
        }
      })
      .finally(onDone);
  },
};
