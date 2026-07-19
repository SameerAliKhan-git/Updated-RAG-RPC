import { API_BASE } from "./client";

export interface CollectionSummary {
  id: string;
  name: string;
  description: string | null;
  paper_count: number;
  created_at: string | null;
  updated_at: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const collectionsApi = {
  list: () => request<{ collections: CollectionSummary[] }>(`/collections`),
  create: (name: string, description?: string) =>
    request<CollectionSummary>(`/collections`, {
      method: "POST",
      body: JSON.stringify({ name, description: description || null }),
    }),
  remove: (id: string) => request<{ status: string }>(`/collections/${id}`, { method: "DELETE" }),
  addPaper: (id: string, arxivId: string) =>
    request<{ status: string }>(`/collections/${id}/papers/${encodeURIComponent(arxivId)}`, { method: "PUT" }),
  removePaper: (id: string, arxivId: string) =>
    request<{ status: string }>(`/collections/${id}/papers/${encodeURIComponent(arxivId)}`, {
      method: "DELETE",
    }),
};
