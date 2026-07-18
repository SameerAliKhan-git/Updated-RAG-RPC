import { AnimatePresence, motion } from "framer-motion";
import { API_BASE } from "../../api/client";

export interface PdfTarget {
  arxivId: string;
  title: string;
}

/** Gemini-style responsive PDF viewer — splits side-by-side on desktop, slides over on mobile. */
export function PdfViewerPanel({
  target,
  onClose,
}: {
  target: PdfTarget | null;
  onClose: () => void;
}) {
  return (
    <AnimatePresence>
      {target && (
        <>
          {/* Scrim: only visible on mobile/tablet, hidden on desktop */}
          <motion.div
            className="fixed inset-0 z-40 lg:hidden"
            style={{ background: "var(--scrim)" }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          
          {/* PDF Panel container: slide-over on mobile/tablet, relative flex child on desktop */}
          <motion.div
            className="fixed inset-y-0 right-0 z-50 flex w-full flex-col md:w-[60%] lg:relative lg:inset-auto lg:z-10 lg:w-1/2 lg:h-full lg:p-4 lg:border-l shrink-0 pdf-panel-responsive"
            style={{ background: "var(--bg)", borderColor: "var(--border)" }}
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ duration: 0.32, ease: [0.2, 0.8, 0.2, 1] }}
          >
            {/* Card UI: rounded with border on desktop */}
            <div
              className="flex flex-col w-full h-full overflow-hidden lg:rounded-2xl lg:border"
              style={{
                background: "var(--bg)",
                borderColor: "var(--border)",
              }}
            >
              {/* Header */}
              <div
                className="flex items-center gap-3 px-4 py-3 shrink-0"
                style={{ borderBottom: "1px solid var(--border)", background: "var(--surface)" }}
              >
                <button
                  aria-label="Close PDF"
                  onClick={onClose}
                  className="rounded-full p-2 transition-colors hover:opacity-75 cursor-pointer"
                  style={{ color: "var(--text-secondary)" }}
                >
                  <CloseIcon />
                </button>
                <span
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[9px] font-bold text-white"
                  style={{ background: "var(--g-red)" }}
                >
                  PDF
                </span>
                <p className="min-w-0 flex-1 truncate text-sm font-medium" style={{ color: "var(--text)" }}>
                  {target.title}
                </p>

                {/* Print button */}
                <button
                  aria-label="Print PDF"
                  onClick={() => {
                    window.open(`${API_BASE}/papers/${encodeURIComponent(target.arxivId)}/pdf`, "_blank");
                  }}
                  className="rounded-full p-2 transition-colors hover:opacity-75 cursor-pointer"
                  style={{ color: "var(--text-secondary)" }}
                >
                  <PrintIcon />
                </button>

                {/* More options button */}
                <button
                  aria-label="More options"
                  className="rounded-full p-2 transition-colors hover:opacity-75 cursor-pointer"
                  style={{ color: "var(--text-secondary)" }}
                >
                  <MoreIcon />
                </button>
              </div>

              {/* Iframe */}
              <iframe
                title={target.title}
                src={`${API_BASE}/papers/${encodeURIComponent(target.arxivId)}/pdf`}
                className="min-h-0 flex-1 border-0 w-full h-full"
                style={{ background: "var(--surface-2)" }}
              />
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function PrintIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="6 9 6 2 18 2 18 9" />
      <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" />
      <rect x="6" y="14" width="12" height="8" />
    </svg>
  );
}

function MoreIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="1" />
      <circle cx="12" cy="5" r="1" />
      <circle cx="12" cy="19" r="1" />
    </svg>
  );
}
