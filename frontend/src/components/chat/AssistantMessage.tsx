import { Fragment, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation, Verification } from "../../api/types";
import { CitationChip } from "./CitationChip";
import { FeedbackBar } from "./FeedbackBar";

function referencesMarkdown(content: string, citations: Citation[]): string {
  if (citations.length === 0) return content;
  const refs = citations
    .map((c) => {
      const authors = c.authors.slice(0, 3).join(", ") + (c.authors.length > 3 ? " et al." : "");
      return `[${c.id}] ${c.paper_title} — ${authors}. arXiv:${c.arxiv_id}. ${c.arxiv_url}`;
    })
    .join("\n");
  return `${content}\n\n## References\n\n${refs}\n`;
}

function bibtex(citations: Citation[]): string {
  return citations
    .map((c) => {
      const key = c.arxiv_id.replace(/[^A-Za-z0-9]/g, "");
      const year = /^(\d{2})/.exec(c.arxiv_id)?.[1];
      return [
        `@article{arxiv${key},`,
        `  title   = {${c.paper_title}},`,
        `  author  = {${c.authors.join(" and ")}},`,
        `  journal = {arXiv preprint arXiv:${c.arxiv_id}},`,
        year ? `  year    = {20${year}},` : null,
        `  url     = {${c.arxiv_url}}`,
        `}`,
      ]
        .filter(Boolean)
        .join("\n");
    })
    .join("\n\n");
}

function ExportMenu({ content, citations }: { content: string; citations: Citation[] }) {
  const [copied, setCopied] = useState<"md" | "bib" | null>(null);

  const copy = async (kind: "md" | "bib") => {
    const text = kind === "md" ? referencesMarkdown(content, citations) : bibtex(citations);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(kind);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      // Clipboard may be unavailable outside secure contexts
    }
  };

  return (
    <span className="inline-flex items-center gap-1.5">
      <button
        onClick={() => void copy("md")}
        className="rounded-full px-3 py-1 text-[11px] font-medium transition-colors"
        style={{ background: "var(--surface)", color: "var(--text-tertiary)" }}
        title="Copy answer with a numbered References section"
      >
        {copied === "md" ? "✓ Copied" : "Copy + citations"}
      </button>
      {citations.length > 0 && (
        <button
          onClick={() => void copy("bib")}
          className="rounded-full px-3 py-1 text-[11px] font-medium transition-colors"
          style={{ background: "var(--surface)", color: "var(--text-tertiary)" }}
          title="Copy sources as BibTeX entries"
        >
          {copied === "bib" ? "✓ Copied" : "BibTeX"}
        </button>
      )}
    </span>
  );
}

function GroundingBar({ verification }: { verification: Verification }) {
  const { verified_claims: verified, total_claims: total, issues } = verification;
  if (!total) return null;
  const ratio = Math.max(0, Math.min(1, verified / total));
  const color = ratio >= 0.9 ? "var(--g-green)" : ratio >= 0.6 ? "var(--g-yellow)" : "var(--g-red)";
  return (
    <span
      className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-[11px] font-medium"
      style={{ background: "var(--surface)", color: "var(--text-secondary)" }}
      title={issues.length ? `${issues.length} claim(s) flagged by verification` : "All claims verified against sources"}
    >
      <span className="inline-block h-1.5 w-16 overflow-hidden rounded-full" style={{ background: "var(--surface-3)" }}>
        <span className="block h-full rounded-full" style={{ width: `${ratio * 100}%`, background: color }} />
      </span>
      {verified}/{total} claims verified
    </span>
  );
}

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
  verification,
  streaming = false,
  sessionId,
  onOpenPdf,
}: {
  content: string;
  citations: Citation[];
  groundingNote?: string;
  cached?: boolean;
  verification?: Verification | null;
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
            {verification ? (
              <GroundingBar verification={verification} />
            ) : (
              groundingNote && (
                <span
                  className="rounded-full px-3 py-1 text-[11px] font-medium"
                  style={{ background: "var(--surface)", color: "var(--text-tertiary)" }}
                >
                  ✓ {groundingNote}
                </span>
              )
            )}
            {cached && (
              <span
                className="rounded-full px-3 py-1 text-[11px] font-medium"
                style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
              >
                ⚡ served from semantic cache
              </span>
            )}
            <ExportMenu content={content} citations={citations} />
            <FeedbackBar sessionId={sessionId} />
          </div>
        )}
      </div>
    </div>
  );
}
