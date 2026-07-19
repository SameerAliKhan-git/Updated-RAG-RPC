import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "../api/client";
import type { ChatSession } from "../api/types";

const STORAGE_KEY = "corpus.sessions";
const MIGRATED_KEY = "corpus.sessions.migrated";

function loadLocal(): ChatSession[] {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]") as ChatSession[];
  } catch {
    return [];
  }
}

function persistLocal(sessions: ChatSession[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.slice(0, 30)));
}

/** Session registry: server (Postgres) is source of truth, localStorage is the
 * offline write-through cache. One-time migration pushes legacy local sessions up. */
export function useSessions() {
  const [sessions, setSessions] = useState<ChatSession[]>(loadLocal);

  useEffect(() => {
    void (async () => {
      try {
        // One-time migration of legacy localStorage sessions
        if (!localStorage.getItem(MIGRATED_KEY)) {
          for (const s of loadLocal()) {
            await fetch(`${API_BASE}/sessions`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ id: s.id, title: s.title }),
            }).catch(() => undefined);
          }
          localStorage.setItem(MIGRATED_KEY, "1");
        }
        const res = await fetch(`${API_BASE}/sessions`);
        if (!res.ok) return;
        const data = (await res.json()) as {
          sessions: { id: string; title: string; updated_at: string | null; collection_id: string | null }[];
        };
        const serverSessions: ChatSession[] = data.sessions.map((s) => ({
          id: s.id,
          title: s.title,
          createdAt: s.updated_at ? Date.parse(s.updated_at) : Date.now(),
        }));
        setSessions(serverSessions);
        persistLocal(serverSessions);
      } catch {
        // Offline — keep the local cache
      }
    })();
  }, []);

  const upsert = useCallback((id: string, title: string) => {
    setSessions((prev) => {
      const rest = prev.filter((s) => s.id !== id);
      const existing = prev.find((s) => s.id === id);
      const next = [{ id, title: existing?.title ?? title, createdAt: existing?.createdAt ?? Date.now() }, ...rest];
      persistLocal(next);
      return next;
    });
    void fetch(`${API_BASE}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, title }),
    }).catch(() => undefined);
  }, []);

  const remove = useCallback((id: string) => {
    setSessions((prev) => {
      const next = prev.filter((s) => s.id !== id);
      persistLocal(next);
      return next;
    });
    void fetch(`${API_BASE}/sessions/${id}`, { method: "DELETE" }).catch(() => undefined);
  }, []);

  return { sessions, upsert, remove };
}
