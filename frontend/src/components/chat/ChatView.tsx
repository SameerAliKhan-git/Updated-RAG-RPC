import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { ChatMessage, Citation } from "../../api/types";
import { useAskStream } from "../../hooks/useAskStream";
import { useSessions } from "../../hooks/useSessions";
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

  const openPdf = useCallback((c: Citation) => {
    setPdfTarget({ arxivId: c.arxiv_id, title: c.paper_title });
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

  // Route change = switching conversations
  useEffect(() => {
    setSessionId(routeSessionId ?? null);
    setMessages(routeSessionId ? loadMessages(routeSessionId) : []);
    reset();
  }, [routeSessionId, reset]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, state.tokens, state.traces.length]);

  const send = useCallback(
    (query: string) => {
      setMessages((prev) => [...prev, { role: "user", content: query }]);
      const filters = attachment?.status === "ready" ? { arxiv_id: attachment.arxivId } : null;
      void ask(query, sessionId, (result) => {
        const sid = result.session_id;
        setSessionId(sid);
        upsert(sid, query.length > 48 ? `${query.slice(0, 48)}…` : query);
        setMessages((prev) => {
          const next: ChatMessage[] = [
            ...prev,
            {
              role: "assistant" as const,
              content: result.answer_markdown,
              citations: result.citations,
              groundingNote: result.grounding_note,
              cached: result.cached,
            },
          ];
          saveMessages(sid, next);
          return next;
        });
      }, filters);
    },
    [ask, sessionId, upsert, attachment],
  );

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
