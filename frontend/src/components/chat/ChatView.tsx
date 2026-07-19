import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { API_BASE, api } from "../../api/client";
import type { ChatMessage, Citation } from "../../api/types";
import { useAskStream } from "../../hooks/useAskStream";
import { useSessions } from "../../hooks/useSessions";
import { setActiveCollection, useActiveCollection } from "../../lib/activeCollection";
import { exportConversation } from "../../lib/exportConversation";
import { AgentTracePanel } from "./AgentTracePanel";
import { AssistantMessage } from "./AssistantMessage";
import { Greeting } from "./Greeting";
import { PdfViewerPanel, type PdfTarget } from "./PdfViewerPanel";
import { PromptBar, type Attachment } from "./PromptBar";
import { SourcesPanel } from "./SourcesPanel";

function loadMessages(sessionId: string): ChatMessage[] {
  try {
    return JSON.parse(localStorage.getItem(`corpus.messages.${sessionId}`) ?? "[]") as ChatMessage[];
  } catch {
    return [];
  }
}

function saveMessages(sessionId: string, messages: ChatMessage[]) {
  localStorage.setItem(`corpus.messages.${sessionId}`, JSON.stringify(messages.slice(-40)));
}

/** Persist the latest user+assistant turn server-side (idempotent by client_msg_id). */
function persistTurn(sessionId: string, userMsg: ChatMessage, assistantMsg: ChatMessage, turnKey: string) {
  void fetch(`${API_BASE}/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify([
      { role: "user", content: userMsg.content, client_msg_id: `${turnKey}-u` },
      {
        role: "assistant",
        content: assistantMsg.content,
        citations: assistantMsg.citations ?? [],
        meta: { grounding_note: assistantMsg.groundingNote, cached: assistantMsg.cached },
        client_msg_id: `${turnKey}-a`,
      },
    ]),
  }).catch(() => undefined);
}

async function loadServerMessages(sessionId: string): Promise<ChatMessage[]> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/messages`);
  if (!res.ok) return [];
  const data = (await res.json()) as {
    messages: { role: "user" | "assistant"; content: string; citations: Citation[]; meta: Record<string, unknown> }[];
  };
  return data.messages.map((m) => ({
    role: m.role,
    content: m.content,
    citations: m.citations,
    groundingNote: (m.meta?.grounding_note as string) || undefined,
    cached: Boolean(m.meta?.cached),
  }));
}

export function ChatView() {
  const { sessionId: routeSessionId } = useParams();
  const [sessionId, setSessionId] = useState<string | null>(routeSessionId ?? null);
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    routeSessionId ? loadMessages(routeSessionId) : [],
  );
  const { state, ask, reset } = useAskStream();
  const { upsert } = useSessions();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [pdfTarget, setPdfTarget] = useState<PdfTarget | null>(null);
  const [attachment, setAttachment] = useState<Attachment | null>(null);
  const [deepVerify, setDeepVerify] = useState(false);
  const [visualOnly, setVisualOnly] = useState(false);
  const activeCollection = useActiveCollection();

  const openPdf = useCallback((c: Citation) => {
    setPdfTarget({ arxivId: c.arxiv_id, title: c.paper_title, page: c.page ?? null, snippet: c.snippet ?? null });
  }, []);

  const attachPdf = useCallback(async (file: File) => {
    setAttachment({ arxivId: "", title: file.name, status: "uploading" });
    try {
      const res = await api.uploadPaper(file, { title: "", authors: "", abstract: "", categories: "" });
      const arxivId = res.stats.arxiv_id;
      if (!arxivId) throw new Error("No paper id returned");
      setAttachment({ arxivId, title: file.name, status: "ready" });
    } catch {
      setAttachment((a) => (a ? { ...a, status: "error" } : null));
    }
  }, []);

  const sendRef = useRef<((q: string) => void) | null>(null);

  // Route change = switching conversations; server history wins over local cache
  useEffect(() => {
    setSessionId(routeSessionId ?? null);
    setMessages(routeSessionId ? loadMessages(routeSessionId) : []);
    reset();
    if (routeSessionId) {
      void loadServerMessages(routeSessionId).then((serverMsgs) => {
        if (serverMsgs.length) {
          setMessages(serverMsgs);
          saveMessages(routeSessionId, serverMsgs);
        }
      });
    }
  }, [routeSessionId, reset]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, state.tokens, state.traces.length]);

  // Galaxy view hands off questions via ?q= — send once, then clean the URL
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const q = params.get("q");
    if (q && !routeSessionId) {
      window.history.replaceState(null, "", window.location.pathname);
      // Defer one tick: sendRef is assigned in a later effect on first mount
      setTimeout(() => sendRef.current?.(q), 50);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const send = useCallback(
    (query: string) => {
      const userMsg: ChatMessage = { role: "user", content: query };
      setMessages((prev) => [...prev, userMsg]);
      const filters: Record<string, unknown> = {};
      if (attachment?.status === "ready") filters.arxiv_id = attachment.arxivId;
      if (visualOnly) filters.chunk_type = ["table", "figure-caption"];
      const turnKey = `${Date.now()}`;
      void ask(
        query,
        sessionId,
        (result) => {
          const sid = result.session_id;
          setSessionId(sid);
          upsert(sid, query.length > 48 ? `${query.slice(0, 48)}…` : query);
          const assistantMsg: ChatMessage = {
            role: "assistant",
            content: result.answer_markdown,
            citations: result.citations,
            groundingNote: result.grounding_note,
            cached: result.cached,
            verification: result.verification,
          };
          setMessages((prev) => {
            const next = [...prev, assistantMsg];
            saveMessages(sid, next);
            return next;
          });
          persistTurn(sid, userMsg, assistantMsg, turnKey);
        },
        Object.keys(filters).length ? filters : null,
        deepVerify,
        activeCollection?.id ?? null,
      );
    },
    [ask, sessionId, upsert, attachment, deepVerify, visualOnly, activeCollection],
  );

  useEffect(() => {
    sendRef.current = send;
  }, [send]);

  const streaming = state.status === "streaming";
  const activeCitations: Citation[] = useMemo(() => {
    if (streaming) return state.citations;
    const last = [...messages].reverse().find((m) => m.role === "assistant");
    return last?.citations ?? [];
  }, [streaming, state.citations, messages]);

  const empty = messages.length === 0 && !streaming;

  return (
    <div className="flex h-full w-full overflow-hidden">
      <div className={`flex min-w-0 flex-1 flex-col transition-all duration-300 ${pdfTarget ? "lg:max-w-[50%]" : "lg:max-w-none"}`}>
        {/* Context bar: collection scope + export */}
        {(activeCollection || messages.length > 0) && (
          <div className="flex items-center gap-2 px-4 pt-3 md:px-8">
            {activeCollection && (
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium"
                style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
              >
                Scoped: {activeCollection.name}
                <button aria-label="Clear scope" onClick={() => setActiveCollection(null)} className="ml-0.5">
                  ×
                </button>
              </span>
            )}
            {messages.length > 0 && (
              <button
                onClick={() =>
                  exportConversation(
                    messages.find((m) => m.role === "user")?.content.slice(0, 60) ?? "Conversation",
                    messages,
                  )
                }
                className="ml-auto rounded-full px-3 py-1 text-xs font-medium transition-colors"
                style={{ background: "var(--surface)", color: "var(--text-secondary)" }}
              >
                ⬇ Export .md
              </button>
            )}
          </div>
        )}
        {empty ? (
          <Greeting onSuggestion={send} />
        ) : (
          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-6 md:px-8">
            <div className="mx-auto flex max-w-3xl flex-col gap-6">
              {messages.map((m, i) =>
                m.role === "user" ? (
                  <UserBubble key={i} text={m.content} />
                ) : (
                  <AssistantMessage
                    key={i}
                    content={m.content}
                    citations={m.citations ?? []}
                    groundingNote={m.groundingNote}
                    cached={m.cached}
                    verification={m.verification}
                    sessionId={sessionId}
                    onOpenPdf={openPdf}
                  />
                ),
              )}

              {streaming && (
                <>
                  <AgentTracePanel traces={state.traces} active />
                  {state.tokens ? (
                    <AssistantMessage
                      content={state.tokens}
                      citations={state.citations}
                      streaming
                      sessionId={sessionId}
                      onOpenPdf={openPdf}
                    />
                  ) : (
                    <p className="gradient-shimmer text-sm font-medium">Thinking…</p>
                  )}
                </>
              )}

              {state.status === "error" && (
                <div
                  className="rounded-2xl px-4 py-3 text-sm"
                  style={{ background: "var(--surface)", color: "var(--g-red)" }}
                >
                  {state.error ?? "Something went wrong."} — verify the FastAPI backend is running on port 8000.
                </div>
              )}
            </div>
          </div>
        )}

        <PromptBar
          onSend={send}
          disabled={streaming}
          centered={empty}
          attachment={attachment}
          onAttach={(file) => void attachPdf(file)}
          onRemoveAttachment={() => setAttachment(null)}
          deepVerify={deepVerify}
          onToggleDeepVerify={() => setDeepVerify((v) => !v)}
          visualOnly={visualOnly}
          onToggleVisualOnly={() => setVisualOnly((v) => !v)}
        />
      </div>

      {/* Sources panel — desktop only (hidden when PDF is open) */}
      {!pdfTarget && activeCitations.length > 0 && (
        <div className="hidden w-80 shrink-0 overflow-y-auto xl:block" style={{ borderLeft: "1px solid var(--border)" }}>
          <SourcesPanel citations={activeCitations} onOpenPdf={openPdf} />
        </div>
      )}

      {/* Gemini-style in-app PDF viewer (responsive split/overlay) */}
      <PdfViewerPanel target={pdfTarget} onClose={() => setPdfTarget(null)} />
    </div>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div
        className="max-w-[85%] rounded-3xl rounded-br-lg px-4 py-2.5 text-[15px]"
        style={{ background: "var(--surface-2)", color: "var(--text)" }}
      >
        {text}
      </div>
    </div>
  );
}
