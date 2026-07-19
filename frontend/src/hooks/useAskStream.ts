import { useCallback, useRef, useState } from "react";
import { API_BASE } from "../api/client";
import type { AskResult, Citation, StreamEvent } from "../api/types";

export interface StreamState {
  status: "idle" | "streaming" | "done" | "error";
  traces: string[];
  tokens: string;
  citations: Citation[];
  result: AskResult | null;
  error: string | null;
}

const INITIAL: StreamState = {
  status: "idle",
  traces: [],
  tokens: "",
  citations: [],
  result: null,
  error: null,
};

/** Consume the POST /stream SSE endpoint via fetch + ReadableStream. */
export function useAskStream() {
  const [state, setState] = useState<StreamState>(INITIAL);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState(INITIAL);
  }, []);

  const ask = useCallback(
    async (
      query: string,
      sessionId: string | null,
      onDone?: (result: AskResult) => void,
      filters?: Record<string, unknown> | null,
      verify?: boolean,
      collectionId?: string | null,
    ) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setState({ ...INITIAL, status: "streaming" });

      try {
        const res = await fetch(`${API_BASE}/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query,
            session_id: sessionId,
            filters: filters ?? null,
            verify: verify ?? false,
            collection_id: collectionId ?? null,
          }),
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          throw new Error(`Backend returned ${res.status}. Is the API running on port 8000?`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // SSE frames are separated by a blank line
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";

          for (const frame of frames) {
            const event = parseFrame(frame);
            if (!event) continue;
            applyEvent(event, setState, onDone);
          }
        }
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        setState((s) => ({ ...s, status: "error", error: (e as Error).message }));
      }
    },
    [],
  );

  return { state, ask, reset };
}

function parseFrame(frame: string): StreamEvent | null {
  let eventType = "";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) eventType = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!eventType || !data) return null;
  try {
    const parsed = JSON.parse(data);
    switch (eventType) {
      case "trace":
        return { type: "trace", step: parsed.step ?? "" };
      case "token":
        return { type: "token", text: parsed.text ?? "" };
      case "citation":
        return { type: "citation", citation: parsed as Citation };
      case "done":
        return { type: "done", result: parsed as AskResult };
      case "error":
        return { type: "error", message: parsed.message ?? "Unknown error" };
      default:
        return null;
    }
  } catch {
    return null;
  }
}

function applyEvent(
  event: StreamEvent,
  setState: React.Dispatch<React.SetStateAction<StreamState>>,
  onDone?: (result: AskResult) => void,
) {
  switch (event.type) {
    case "trace":
      setState((s) => ({ ...s, traces: [...s.traces, event.step] }));
      break;
    case "token":
      setState((s) => ({ ...s, tokens: s.tokens + event.text }));
      break;
    case "citation":
      setState((s) => ({ ...s, citations: [...s.citations, event.citation] }));
      break;
    case "done":
      // The done payload carries the post-verification answer — replace streamed text.
      setState((s) => ({
        ...s,
        status: "done",
        tokens: event.result.answer_markdown,
        citations: event.result.citations,
        result: event.result,
      }));
      onDone?.(event.result);
      break;
    case "error":
      setState((s) => ({ ...s, status: "error", error: event.message }));
      break;
  }
}
