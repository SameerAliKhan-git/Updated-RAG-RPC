import type { Citation } from "../../api/types";

export function SourcesPanel({
  citations,
  onOpenPdf,
}: {
  citations: Citation[];
  onOpenPdf?: (citation: Citation) => void;
}) {
  return (
    <div className="flex flex-col gap-3 p-5">
      <h2 className="text-sm font-semibold" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-display)" }}>
        Sources in context
      </h2>
      {citations.map((c) => (
        <button
          key={c.id}
          onClick={() => onOpenPdf?.(c)}
          className="group rounded-3xl p-4 text-left transition-all hover:-translate-y-0.5 hover:shadow-md"
          style={{ background: "var(--surface)" }}
        >
          <div className="flex items-start gap-2.5">
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white"
              style={{ background: "var(--gradient-gemini-solid)" }}
            >
              {c.id}
            </span>
            <div className="min-w-0">
              <p className="line-clamp-2 text-[13px] font-medium leading-snug" style={{ color: "var(--text)" }}>
                {c.paper_title}
              </p>
              <p className="mt-1 text-[11px]" style={{ color: "var(--text-tertiary)" }}>
                {c.authors.slice(0, 3).join(", ")}
                {c.authors.length > 3 ? " et al." : ""}
              </p>
              <p className="mt-0.5 text-[11px]" style={{ color: "var(--text-tertiary)" }}>
                {c.section} · {c.arxiv_id}
              </p>
              {c.snippet && (
                <p className="mt-2 line-clamp-3 text-[12px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                  “{c.snippet}”
                </p>
              )}
            </div>
          </div>
        </button>
      ))}
    </div>
  );
}
