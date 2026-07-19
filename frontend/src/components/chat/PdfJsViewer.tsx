import { useCallback, useEffect, useRef, useState } from "react";
import { buildPageString, findSnippetRange, itemsInRange } from "../../lib/snippetMatch";

interface HighlightRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Page-at-a-time PDF.js renderer with fuzzy citation-snippet highlighting. */
export function PdfJsViewer({
  url,
  initialPage,
  snippet,
}: {
  url: string;
  initialPage: number;
  snippet?: string | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const docRef = useRef<unknown>(null);
  const renderTaskRef = useRef<{ cancel: () => void } | null>(null);
  const [pageNum, setPageNum] = useState(initialPage || 1);
  const [pageCount, setPageCount] = useState(0);
  const [highlights, setHighlights] = useState<HighlightRect[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [matchState, setMatchState] = useState<"none" | "found" | "missed">("none");

  const renderPage = useCallback(
    async (doc: unknown, num: number) => {
      const pdfjs = await import("pdfjs-dist");
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const page = await (doc as any).getPage(num);
      const container = containerRef.current;
      const canvas = canvasRef.current;
      if (!container || !canvas) return;

      const baseViewport = page.getViewport({ scale: 1 });
      const scale = Math.max(0.5, (container.clientWidth - 24) / baseViewport.width);
      const viewport = page.getViewport({ scale });

      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;

      renderTaskRef.current?.cancel();
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const task = page.render({
        canvasContext: ctx,
        viewport,
        transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
      });
      renderTaskRef.current = task;
      try {
        await task.promise;
      } catch {
        return; // cancelled by a newer render
      }

      // Snippet highlighting on the citation's page only
      if (snippet && num === initialPage) {
        try {
          const textContent = await page.getTextContent();
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const items = textContent.items as any[];
          const { page: pageNorm, refs } = buildPageString(items.map((it) => String(it.str ?? "")));
          const range = findSnippetRange(pageNorm, snippet);
          if (range) {
            const matched = new Set(itemsInRange(refs, range[0], range[1]));
            const rects: HighlightRect[] = [];
            items.forEach((item, idx) => {
              if (!matched.has(idx) || !item.str?.trim()) return;
              const tx = pdfjs.Util.transform(viewport.transform, item.transform);
              const fontHeight = Math.hypot(tx[2], tx[3]);
              rects.push({
                x: tx[4],
                y: tx[5] - fontHeight,
                width: (item.width ?? 0) * scale,
                height: fontHeight * 1.15,
              });
            });
            setHighlights(rects);
            setMatchState(rects.length ? "found" : "missed");
            if (rects.length) {
              // Scroll the first highlight into view
              const top = Math.max(0, rects[0].y - 120);
              container.scrollTo({ top, behavior: "smooth" });
            }
          } else {
            setHighlights([]);
            setMatchState("missed");
          }
        } catch {
          setHighlights([]);
          setMatchState("missed");
        }
      } else {
        setHighlights([]);
      }
    },
    [snippet, initialPage],
  );

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        // @ts-expect-error — Vite ?url import has no type declaration
        const workerUrl = (await import("pdfjs-dist/build/pdf.worker.min.mjs?url")).default as string;
        pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
        const doc = await pdfjs.getDocument(url).promise;
        if (cancelled) return;
        docRef.current = doc;
        setPageCount(doc.numPages);
        const target = Math.min(Math.max(1, initialPage || 1), doc.numPages);
        setPageNum(target);
        await renderPage(doc, target);
        if (!cancelled) setStatus("ready");
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();
    return () => {
      cancelled = true;
      renderTaskRef.current?.cancel();
    };
  }, [url, initialPage, renderPage]);

  const goTo = useCallback(
    (num: number) => {
      const doc = docRef.current;
      if (!doc || num < 1 || num > pageCount) return;
      setPageNum(num);
      void renderPage(doc, num);
    },
    [pageCount, renderPage],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Page controls */}
      <div
        className="flex items-center justify-center gap-3 px-4 py-1.5 text-xs"
        style={{ background: "var(--surface)", borderBottom: "1px solid var(--border)", color: "var(--text-secondary)" }}
      >
        <button onClick={() => goTo(pageNum - 1)} disabled={pageNum <= 1} className="rounded-full px-2 py-0.5 disabled:opacity-30">
          ‹ Prev
        </button>
        <span>
          Page {pageNum} / {pageCount || "…"}
        </span>
        <button onClick={() => goTo(pageNum + 1)} disabled={pageNum >= pageCount} className="rounded-full px-2 py-0.5 disabled:opacity-30">
          Next ›
        </button>
        {matchState === "found" && pageNum === initialPage && (
          <span className="rounded-full px-2 py-0.5" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
            passage highlighted
          </span>
        )}
        {matchState === "missed" && pageNum === initialPage && (
          <span style={{ color: "var(--text-tertiary)" }}>passage not located — showing page</span>
        )}
      </div>

      <div ref={containerRef} className="relative min-h-0 flex-1 overflow-auto p-3" style={{ background: "var(--surface-2)" }}>
        {status === "loading" && (
          <p className="gradient-shimmer p-6 text-center text-sm font-medium">Loading PDF…</p>
        )}
        {status === "error" && (
          <p className="p-6 text-center text-sm" style={{ color: "var(--g-red)" }}>
            Could not render this PDF.
          </p>
        )}
        <div className="relative mx-auto w-fit">
          <canvas ref={canvasRef} className="rounded-lg shadow-md" />
          {highlights.map((r, i) => (
            <div
              key={i}
              className="pointer-events-none absolute rounded-sm"
              style={{
                left: r.x,
                top: r.y,
                width: r.width,
                height: r.height,
                background: "rgba(251, 188, 4, 0.4)",
                mixBlendMode: "multiply",
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export default PdfJsViewer;
