import type { EvalHistoryEntry, EvalStatus, HealthStatus, PaperListResponse, PaperSummary } from "./types";

export const API_BASE = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${body ? ` — ${body.slice(0, 200)}` : ""}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listPapers: (page = 1, perPage = 24, search?: string, status?: string) =>
    request<PaperListResponse>(
      `/papers?page=${page}&per_page=${perPage}` +
        (search ? `&search=${encodeURIComponent(search)}` : "") +
        (status ? `&status=${status}` : ""),
    ),

  patchPaper: (arxivId: string, body: { reading_status?: string; notes?: string }) =>
    request<{ arxiv_id: string; reading_status: string }>(`/papers/${encodeURIComponent(arxivId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  zoteroImport: (useLocal = true, apiKey?: string, userId?: string) =>
    request<{ queued: unknown[]; already_present: unknown[]; skipped: unknown[] }>(
      `/integrations/zotero/import`,
      {
        method: "POST",
        body: JSON.stringify({ use_local: useLocal, api_key: apiKey || null, zotero_user_id: userId || null }),
      },
    ),

  getPaper: (arxivId: string) => request<PaperSummary & { chunks: unknown[] }>(`/papers/${arxivId}`),

  health: () => request<HealthStatus>(`/health`),

  evalStatus: () => request<EvalStatus>(`/eval/status`),

  evalHistory: (limit = 30) =>
    request<{ history: EvalHistoryEntry[] }>(`/eval/history?limit=${limit}`),

  runEval: () =>
    request<{ status: string; message: string }>(`/eval/run?mode=golden&limit=5`, { method: "POST" }),

  sendFeedback: (queryId: string, rating: "up" | "down", correction?: string) =>
    request<{ status: string }>(`/feedback`, {
      method: "POST",
      body: JSON.stringify({ query_id: queryId, rating, correction: correction || null }),
    }),

  extractMetadata: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/papers/extract-metadata`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`Metadata extraction failed (${res.status})`);
    return res.json() as Promise<{ title: string; authors: string[]; abstract: string }>;
  },

  uploadPaper: async (
    file: File,
    meta: { title: string; authors: string; abstract: string; categories: string },
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("title", meta.title);
    form.append("authors", meta.authors);
    form.append("abstract", meta.abstract);
    form.append("categories", meta.categories);
    const res = await fetch(`${API_BASE}/papers/upload`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`Upload failed (${res.status})`);
    return res.json() as Promise<{ status: string; stats: { arxiv_id?: string } & Record<string, unknown> }>;
  },

  paperPdfUrl: (arxivId: string) => `${API_BASE}/papers/${encodeURIComponent(arxivId)}/pdf`,
};
