import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { API_BASE } from "../../api/client";
import { getActiveCollection } from "../../lib/activeCollection";

interface ResearchState {
  id: string;
  topic: string;
  status: "planning" | "researching" | "done" | "failed";
  steps: string[];
  result_markdown: string | null;
  error?: string;
}

export function ResearchView() {
  const [topic, setTopic] = useState("");
  const [job, setJob] = useState<ResearchState | null>(null);
  const pollRef = useRef<number>(0);

  const start = async () => {
    const t = topic.trim();
    if (!t) return;
    const collection = getActiveCollection();
    const res = await fetch(`${API_BASE}/research`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic: t, collection_id: collection?.id ?? null }),
    });
    if (!res.ok) return;
    const data = (await res.json()) as ResearchState;
    setJob({ ...data, steps: [], result_markdown: null });
  };

  useEffect(() => {
    if (!job || job.status === "done" || job.status === "failed") return;
    pollRef.current = window.setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/research/${job.id}`);
        if (res.ok) setJob((await res.json()) as ResearchState);
      } catch {
        // transient poll failure — keep trying
      }
    }, 3000);
    return () => clearInterval(pollRef.current);
  }, [job?.id, job?.status]);

  const download = () => {
    if (!job?.result_markdown) return;
    const blob = new Blob([job.result_markdown], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `corpus-research-${job.topic.slice(0, 30).replace(/\W+/g, "-")}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const running = job && (job.status === "planning" || job.status === "researching");

  return (
    <div className="h-full overflow-y-auto px-4 py-6 md:px-8">
      <div className="mx-auto max-w-3xl">
        <h1 className="gradient-text text-2xl font-semibold" style={{ fontFamily: "var(--font-display)" }}>
          Deep Research
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--text-tertiary)" }}>
          A background agent plans sub-topics, searches your corpus, and writes a fully-cited literature review.
          {getActiveCollection() ? ` Scoped to: ${getActiveCollection()!.name}.` : ""}
        </p>

        <div
          className="mt-6 flex items-end gap-2 rounded-3xl px-5 py-3"
          style={{ background: "var(--surface)" }}
        >
          <textarea
            value={topic}
            rows={1}
            placeholder="e.g. Efficient attention mechanisms in transformers"
            onChange={(e) => setTopic(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void start();
              }
            }}
            disabled={!!running}
            className="flex-1 resize-none bg-transparent py-1 text-[15px] outline-none"
            style={{ color: "var(--text)" }}
          />
          <button
            onClick={() => void start()}
            disabled={!!running || !topic.trim()}
            className="rounded-full px-5 py-2 text-sm font-medium text-white disabled:opacity-40"
            style={{ background: "var(--gradient-gemini-solid)" }}
          >
            {running ? "Researching…" : "Research"}
          </button>
        </div>

        {job && (
          <div className="mt-6 rounded-3xl p-5" style={{ background: "var(--surface)" }}>
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium" style={{ color: "var(--text)" }}>
                {job.topic}
              </p>
              {job.status === "done" && (
                <button
                  onClick={download}
                  className="rounded-full px-4 py-1.5 text-xs font-medium"
                  style={{ background: "var(--surface-2)", color: "var(--text-secondary)" }}
                >
                  Download .md
                </button>
              )}
            </div>

            <ol className="mt-3 flex flex-col gap-1.5">
              {job.steps.map((s, i) => {
                const isLast = i === job.steps.length - 1;
                return (
                  <li key={i} className="flex items-start gap-2.5 text-[13px]">
                    <span
                      className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                      style={{
                        background: isLast && running ? "var(--gradient-gemini-solid)" : "var(--surface-3)",
                      }}
                    />
                    <span
                      className={isLast && running ? "gradient-shimmer font-medium" : ""}
                      style={{ color: isLast && running ? undefined : "var(--text-tertiary)" }}
                    >
                      {s}
                    </span>
                  </li>
                );
              })}
            </ol>

            {job.status === "failed" && (
              <p className="mt-3 text-sm" style={{ color: "var(--g-red)" }}>
                Research failed: {job.error ?? "unknown error"}
              </p>
            )}
          </div>
        )}

        {job?.result_markdown && (
          <div className="prose-answer mt-6 rounded-3xl p-6" style={{ background: "var(--surface)" }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{job.result_markdown}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}
