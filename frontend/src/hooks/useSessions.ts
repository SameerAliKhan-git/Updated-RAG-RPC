import { useCallback, useState } from "react";
import type { ChatSession } from "../api/types";

const STORAGE_KEY = "corpus.sessions";

function load(): ChatSession[] {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]") as ChatSession[];
  } catch {
    return [];
  }
}

function persist(sessions: ChatSession[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.slice(0, 30)));
}

/** Client-side registry of recent chat sessions (session_id continuity lives server-side in Redis). */
export function useSessions() {
  const [sessions, setSessions] = useState<ChatSession[]>(load);

  const upsert = useCallback((id: string, title: string) => {
    setSessions((prev) => {
      const rest = prev.filter((s) => s.id !== id);
      const existing = prev.find((s) => s.id === id);
      const next = [{ id, title: existing?.title ?? title, createdAt: existing?.createdAt ?? Date.now() }, ...rest];
      persist(next);
      return next;
    });
  }, []);

  const remove = useCallback((id: string) => {
    setSessions((prev) => {
      const next = prev.filter((s) => s.id !== id);
      persist(next);
      return next;
    });
  }, []);

  return { sessions, upsert, remove };
}
