import { useState } from "react";
import { api } from "../../api/client";

type Stage = "pick" | "extracting" | "review" | "uploading" | "error";

export function UploadModal({ onClose, onUploaded }: { onClose: () => void; onUploaded: () => void }) {
  const [stage, setStage] = useState<Stage>("pick");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [authors, setAuthors] = useState("");
  const [abstract, setAbstract] = useState("");
  const [categories, setCategories] = useState("");
  const [error, setError] = useState("");

  const pickFile = async (picked: File) => {
    setFile(picked);
    setStage("extracting");
    try {
      const meta = await api.extractMetadata(picked);
      setTitle(meta.title);
      setAuthors(meta.authors.join(", "));
      setAbstract(meta.abstract);
      setStage("review");
    } catch {
      // Extraction is best-effort — let the user fill fields manually
      setStage("review");
    }
  };

  const upload = async () => {
    if (!file) return;
    setStage("uploading");
    try {
      await api.uploadPaper(file, { title, authors, abstract, categories });
      onUploaded();
    } catch (e) {
      setError((e as Error).message);
      setStage("error");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0" style={{ background: "var(--scrim)" }} onClick={onClose} />
      <div
        className="relative z-10 w-full max-w-lg rounded-3xl p-6"
        style={{ background: "var(--bg)", boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}
      >
        <h2 className="text-lg font-semibold" style={{ fontFamily: "var(--font-display)" }}>
          Upload a paper
        </h2>

        {stage === "pick" && (
          <label
            className="mt-5 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-3xl border-2 border-dashed p-10 text-sm transition-colors"
            style={{ borderColor: "var(--border)", color: "var(--text-tertiary)" }}
          >
            <span className="gradient-text text-base font-medium">Choose a PDF</span>
            <span>Metadata will be auto-extracted with Docling</span>
            <input
              type="file"
              accept="application/pdf"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void pickFile(f);
              }}
            />
          </label>
        )}

        {stage === "extracting" && (
          <p className="gradient-shimmer mt-6 py-8 text-center text-sm font-medium">
            Extracting title, authors, and abstract…
          </p>
        )}

        {(stage === "review" || stage === "uploading" || stage === "error") && (
          <div className="mt-5 flex flex-col gap-3">
            <Field label="Title" value={title} onChange={setTitle} />
            <Field label="Authors (comma-separated)" value={authors} onChange={setAuthors} />
            <Field label="Abstract" value={abstract} onChange={setAbstract} multiline />
            <Field label="Categories (e.g. cs.AI, cs.CL)" value={categories} onChange={setCategories} />

            {stage === "error" && (
              <p className="text-xs" style={{ color: "var(--g-red)" }}>
                {error}
              </p>
            )}

            <div className="mt-2 flex justify-end gap-3">
              <button
                onClick={onClose}
                className="rounded-full px-5 py-2 text-sm font-medium"
                style={{ background: "var(--surface)", color: "var(--text-secondary)" }}
              >
                Cancel
              </button>
              <button
                onClick={() => void upload()}
                disabled={stage === "uploading" || !title.trim()}
                className="rounded-full px-5 py-2 text-sm font-medium text-white disabled:opacity-50"
                style={{ background: "var(--gradient-gemini-solid)" }}
              >
                {stage === "uploading" ? "Ingesting…" : "Upload & index"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  multiline = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  multiline?: boolean;
}) {
  const cls = "w-full rounded-2xl px-4 py-2.5 text-sm outline-none";
  const style = { background: "var(--surface)", color: "var(--text)" };
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium" style={{ color: "var(--text-tertiary)" }}>
        {label}
      </span>
      {multiline ? (
        <textarea rows={3} value={value} onChange={(e) => onChange(e.target.value)} className={cls} style={style} />
      ) : (
        <input value={value} onChange={(e) => onChange(e.target.value)} className={cls} style={style} />
      )}
    </label>
  );
}
