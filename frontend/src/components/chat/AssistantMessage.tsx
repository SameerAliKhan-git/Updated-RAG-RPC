import { Fragment, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation } from "../../api/types";
import { CitationChip } from "./CitationChip";
import { FeedbackBar } from "./FeedbackBar";

/** Split "[N]" citation markers inside text nodes into CitationChip components. */
function withCitationChips(
  children: ReactNode,
  citations: Citation[],
  onOpenPdf?: (citation: Citation) => void,
): ReactNode {
  const mapChild = (child: ReactNode, key: number): ReactNode => {
    if (typeof child !== "string") return child;
    const parts = child.split(/(\[\d+\])/g);
    if (parts.length === 1) return child;
    return (
      <Fragment key={key}>
        {parts.map((part, i) => {
          const match = /^\[(\d+)\]$/.exec(part);
          if (!match) return part;
          const id = Number(match[1]);
          const citation = citations.find((c) => c.id === id);
          return <CitationChip key={i} id={id} citation={citation} onOpen={onOpenPdf} />;
        })}
      </Fragment>
    );
  };
  if (Array.isArray(children)) return children.map(mapChild);
  return mapChild(children, 0);
}

export function AssistantMessage({
  content,
  citations,
  groundingNote,
  cached,
  streaming = false,
  sessionId,
  onOpenPdf,
}: {
  content: string;
  citations: Citation[];
  groundingNote?: string;
  cached?: boolean;
  streaming?: boolean;
  sessionId: string | null;
  onOpenPdf?: (citation: Citation) => void;
}) {
  return (
    <div className="flex gap-3">
      <div
        className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white"
        style={{ background: "var(--gradient-gemini-solid)" }}
      >
        C
      </div>
      <div className="min-w-0 flex-1">
        <div className={`prose-answer ${streaming ? "token-cursor" : ""}`}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => <p>{withCitationChips(children, citations, onOpenPdf)}</p>,
              li: ({ children }) => <li>{withCitationChips(children, citations, onOpenPdf)}</li>,
              td: ({ children }) => <td>{withCitationChips(children, citations, onOpenPdf)}</td>,
              blockquote: ({ children }) => <blockquote>{children}</blockquote>,
            }}
          >
            {content}
          </ReactMarkdown>
        </div>

        {!streaming && (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            {groundingNote && (
              <span
                className="rounded-full px-3 py-1 text-[11px] font-medium"
                style={{ background: "var(--surface)", color: "var(--text-tertiary)" }}
              >
                ✓ {groundingNote}
              </span>
            )}
            {cached && (
              <span
                className="rounded-full px-3 py-1 text-[11px] font-medium"
                style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
              >
                ⚡ served from semantic cache
              </span>
            )}
            <FeedbackBar sessionId={sessionId} />
          </div>
        )}
      </div>
    </div>
  );
}
