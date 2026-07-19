import { useQuery } from "@tanstack/react-query";
import { API_BASE } from "../../api/client";

interface VisualChunk {
  chunk_id: string;
  section_title: string;
  chunk_type: string;
  text: string;
  page_number?: number | null;
}

const TYPE_LABEL: Record<string, string> = {
  table: "Table",
  "figure-caption": "Figure",
  equation: "Equation",
};

/** Extract the LLM visual summary prepended at ingestion, if present. */
function summaryOf(text: string): { summary: string | null; body: string } {
  const match = /^\[Visual Layout Summary:\s*([\s\S]*?)\]\s*/.exec(text);
  if (!match) return { summary: null, body: text };
  return { summary: match[1].trim(), body: text.slice(match[0].length) };
}

export function FiguresModal({
  arxivId,
  title,
  onClose,
  onOpenPdf,
}: {
  arxivId: string;
  title: string;
  onClose: () => void;
  onOpenPdf: (page: number | null) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["paperDetail", arxivId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/papers/${encodeURIComponent(arxivId)}`);
      if (!res.ok) throw new Error(`${res.status}`);
      return res.json() as Promise<{ chunks: VisualChunk[] }>;
    },
  });

  const visuals = (data?.chunks ?? []).filter((c) =>
    ["table", "figure-caption", "equation"].includes(c.chunk_type),
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0" style={{ background: "var(--scrim)" }} onClick={onClose} />
      <div
        className="relative z-10 flex max-h-[80vh] w-full max-w-2xl flex-col rounded-3xl p-6"
        style={{ background: "var(--bg)", boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}
      >
        <h2 className="pr-8 text-base font-semibold leading-snug" style={{ fontFamily: "var(--font-display)" }}>
          Figures & Tables — {title}
        </h2>
        <button
          aria-label="Close"
          onClick={onClose}
          className="absolute right-5 top-5 rounded-full p-1.5"
          style={{ color: "var(--text-tertiary)" }}
        >
          ✕
        </button>

        <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
          {isLoading && <p className="gradient-shimmer py-6 text-center text-sm font-medium">Loading…</p>}
          {!isLoading && visuals.length === 0 && (
            <p className="py-6 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>
              No tables, figures, or equations were extracted from this paper.
            </p>
          )}
          <div className="flex flex-col gap-3">
            {visuals.map((c) => {
              const { summary, body } = summaryOf(c.text);
              return (
                <button
                  key={c.chunk_id}
                  onClick={() => onOpenPdf(c.page_number ?? null)}
                  className="rounded-2xl p-4 text-left transition-all hover:-translate-y-0.5 hover:shadow-md"
                  style={{ background: "var(--surface)" }}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className="rounded-full px-2.5 py-0.5 text-[10px] font-semibold"
                      style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
                    >
                      {TYPE_LABEL[c.chunk_type] ?? c.chunk_type}
                    </span>
                    <span className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
                      {c.section_title}
                      {c.page_number ? ` · p. ${c.page_number}` : ""}
                    </span>
                  </div>
                  {summary && (
                    <p className="mt-2 text-[13px] font-medium leading-relaxed" style={{ color: "var(--text)" }}>
                      {summary}
                    </p>
                  )}
                  <p className="mt-1.5 line-clamp-3 whitespace-pre-wrap text-[12px]" style={{ color: "var(--text-secondary)" }}>
                    {body}
                  </p>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
