import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { collectionsApi } from "../../api/collections";
import type { ReadingStatus } from "../../api/types";
import { UploadModal } from "./UploadModal";

const STATUS_CHIPS: { value: string; label: string }[] = [
  { value: "", label: "All" },
  { value: "to_read", label: "To read" },
  { value: "reading", label: "Reading" },
  { value: "done", label: "Done" },
];

const STATUS_OPTIONS: { value: ReadingStatus; label: string }[] = [
  { value: "unread", label: "Unread" },
  { value: "to_read", label: "To read" },
  { value: "reading", label: "Reading" },
  { value: "done", label: "Done" },
];

export function LibraryView() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [zoteroBusy, setZoteroBusy] = useState(false);
  const [zoteroMsg, setZoteroMsg] = useState("");
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["papers", page, search, status],
    queryFn: () => api.listPapers(page, 24, search || undefined, status || undefined),
  });

  const collections = useQuery({ queryKey: ["collections"], queryFn: collectionsApi.list, staleTime: 15_000 });

  const setPaperStatus = async (arxivId: string, readingStatus: string) => {
    await api.patchPaper(arxivId, { reading_status: readingStatus });
    void queryClient.invalidateQueries({ queryKey: ["papers"] });
  };

  const addToCollection = async (collectionId: string, arxivId: string) => {
    await collectionsApi.addPaper(collectionId, arxivId);
    void queryClient.invalidateQueries({ queryKey: ["collections"] });
  };

  const importZotero = async () => {
    setZoteroBusy(true);
    setZoteroMsg("");
    try {
      const res = await api.zoteroImport(true);
      setZoteroMsg(
        `Zotero: ${res.queued.length} queued for ingestion, ${res.already_present.length} already here, ${res.skipped.length} skipped.`,
      );
    } catch (e) {
      setZoteroMsg((e as Error).message.includes("502")
        ? "Zotero import failed — is the Zotero desktop app running?"
        : `Zotero import failed: ${(e as Error).message}`);
    } finally {
      setZoteroBusy(false);
    }
  };

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
          <div className="flex items-center gap-2">
            <button
              onClick={() => void importZotero()}
              disabled={zoteroBusy}
              className="rounded-full px-4 py-2.5 text-sm font-medium transition-all disabled:opacity-50"
              style={{ background: "var(--surface)", color: "var(--text-secondary)" }}
              title="Import arXiv papers from your Zotero desktop library"
            >
              {zoteroBusy ? "Importing…" : "Import from Zotero"}
            </button>
            <button
              onClick={() => setUploadOpen(true)}
              className="rounded-full px-5 py-2.5 text-sm font-medium text-white transition-all hover:shadow-lg"
              style={{ background: "var(--gradient-gemini-solid)" }}
            >
              Upload PDF
            </button>
          </div>
        </div>

        {zoteroMsg && (
          <p className="mt-3 text-sm" style={{ color: "var(--text-secondary)" }}>
            {zoteroMsg}
          </p>
        )}

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            placeholder="Search title, abstract, author, category…"
            className="w-full max-w-xl rounded-full px-5 py-3 text-sm outline-none"
            style={{ background: "var(--surface)", color: "var(--text)" }}
          />
          <div className="flex gap-1.5">
            {STATUS_CHIPS.map((chip) => (
              <button
                key={chip.value}
                onClick={() => {
                  setStatus(chip.value);
                  setPage(1);
                }}
                className="rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors"
                style={{
                  background: status === chip.value ? "var(--accent-soft)" : "var(--surface)",
                  color: status === chip.value ? "var(--accent)" : "var(--text-secondary)",
                }}
              >
                {chip.label}
              </button>
            ))}
          </div>
        </div>

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
                <div
                  key={p.arxiv_id}
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
                  <a
                    href={p.arxiv_id.startsWith("upload_") ? undefined : `https://arxiv.org/abs/${p.arxiv_id}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <h3 className="mt-3 line-clamp-2 text-[15px] font-medium leading-snug hover:underline" style={{ color: "var(--text)" }}>
                      {p.title}
                    </h3>
                  </a>
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
                  <div className="mt-3 flex items-center gap-2">
                    <select
                      value={p.reading_status}
                      onChange={(e) => void setPaperStatus(p.arxiv_id, e.target.value)}
                      className="rounded-full px-2.5 py-1 text-[11px] outline-none"
                      style={{ background: "var(--surface-2)", color: "var(--text-secondary)" }}
                      aria-label="Reading status"
                    >
                      {STATUS_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                    {(collections.data?.collections.length ?? 0) > 0 && (
                      <select
                        value=""
                        onChange={(e) => {
                          if (e.target.value) void addToCollection(e.target.value, p.arxiv_id);
                          e.target.value = "";
                        }}
                        className="rounded-full px-2.5 py-1 text-[11px] outline-none"
                        style={{ background: "var(--surface-2)", color: "var(--text-secondary)" }}
                        aria-label="Add to collection"
                      >
                        <option value="">+ Collection…</option>
                        {collections.data?.collections.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.name}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                </div>
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
