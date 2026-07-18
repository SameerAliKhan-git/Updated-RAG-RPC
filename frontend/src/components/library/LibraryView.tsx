import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { UploadModal } from "./UploadModal";

export function LibraryView() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [uploadOpen, setUploadOpen] = useState(false);
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["papers", page, search],
    queryFn: () => api.listPapers(page, 24, search || undefined),
  });

  return (
    <div className="h-full overflow-y-auto px-4 py-6 md:px-8">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold" style={{ fontFamily: "var(--font-display)" }}>
              Library
            </h1>
            <p className="mt-1 text-sm" style={{ color: "var(--text-tertiary)" }}>
              {data ? `${data.total} papers indexed` : "Ingested research papers"}
            </p>
          </div>
          <button
            onClick={() => setUploadOpen(true)}
            className="rounded-full px-5 py-2.5 text-sm font-medium text-white transition-all hover:shadow-lg"
            style={{ background: "var(--gradient-gemini-solid)" }}
          >
            Upload PDF
          </button>
        </div>

        <input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          placeholder="Search title, abstract, author, category…"
          className="mt-6 w-full max-w-xl rounded-full px-5 py-3 text-sm outline-none"
          style={{ background: "var(--surface)", color: "var(--text)" }}
        />

        {isLoading && <SkeletonGrid />}
        {error != null && (
          <p className="mt-8 text-sm" style={{ color: "var(--g-red)" }}>
            Failed to load papers — is the backend running on port 8000?
          </p>
        )}

        {data && (
          <>
            <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {data.papers.map((p) => (
                <a
                  key={p.arxiv_id}
                  href={p.arxiv_id.startsWith("upload_") ? undefined : `https://arxiv.org/abs/${p.arxiv_id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="flex flex-col rounded-3xl p-5 transition-all hover:-translate-y-0.5 hover:shadow-lg"
                  style={{ background: "var(--surface)" }}
                >
                  <div className="flex flex-wrap gap-1.5">
                    {p.categories.slice(0, 3).map((cat, i) => (
                      <span
                        key={cat}
                        className="rounded-full px-2.5 py-0.5 text-[10px] font-medium"
                        style={{
                          background: "var(--surface-2)",
                          color: ["var(--g-blue)", "var(--g-green)", "#9b72cb"][i % 3],
                        }}
                      >
                        {cat}
                      </span>
                    ))}
                  </div>
                  <h3 className="mt-3 line-clamp-2 text-[15px] font-medium leading-snug" style={{ color: "var(--text)" }}>
                    {p.title}
                  </h3>
                  <p className="mt-1.5 text-xs" style={{ color: "var(--text-tertiary)" }}>
                    {p.authors.slice(0, 3).join(", ")}
                    {p.authors.length > 3 ? " et al." : ""}
                  </p>
                  <p className="mt-2 line-clamp-3 flex-1 text-[13px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                    {p.abstract}
                  </p>
                  <div className="mt-3 flex items-center gap-3 text-[11px]" style={{ color: "var(--text-tertiary)" }}>
                    <span>{p.published_date?.slice(0, 10)}</span>
                    <span>·</span>
                    <span>{p.chunk_count} chunks</span>
                    {p.pdf_processed && <span style={{ color: "var(--g-green)" }}>✓ indexed</span>}
                  </div>
                </a>
              ))}
            </div>

            {data.total > 24 && (
              <div className="mt-8 flex items-center justify-center gap-4">
                <PageButton label="Previous" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} />
                <span className="text-sm" style={{ color: "var(--text-tertiary)" }}>
                  Page {page} of {Math.ceil(data.total / 24)}
                </span>
                <PageButton
                  label="Next"
                  disabled={page >= Math.ceil(data.total / 24)}
                  onClick={() => setPage((p) => p + 1)}
                />
              </div>
            )}
          </>
        )}
      </div>

      {uploadOpen && (
        <UploadModal
          onClose={() => setUploadOpen(false)}
          onUploaded={() => {
            setUploadOpen(false);
            void queryClient.invalidateQueries({ queryKey: ["papers"] });
          }}
        />
      )}
    </div>
  );
}

function PageButton({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className="rounded-full px-4 py-2 text-sm font-medium transition-colors disabled:opacity-40"
      style={{ background: "var(--surface)", color: "var(--text-secondary)" }}
    >
      {label}
    </button>
  );
}

function SkeletonGrid() {
  return (
    <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-48 animate-pulse rounded-3xl" style={{ background: "var(--surface)" }} />
      ))}
    </div>
  );
}
