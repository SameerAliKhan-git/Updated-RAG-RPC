import { useState } from "react";
import type { Citation } from "../../api/types";

export function CitationChip({
  id,
  citation,
  onOpen,
}: {
  id: number;
  citation?: Citation;
  onOpen?: (citation: Citation) => void;
}) {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <span
      role="button"
      tabIndex={0}
      onClick={() => citation && onOpen?.(citation)}
      onKeyDown={(e) => {
        if (e.key === "Enter" && citation) onOpen?.(citation);
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className="relative mx-1 inline-flex cursor-pointer select-none items-center justify-center rounded-md px-1.5 py-0.5 align-middle text-[10px] font-semibold transition-all hover:scale-105"
      style={{
        background: "var(--surface-3)",
        color: "var(--text-secondary)",
        border: "1px solid var(--border)",
      }}
    >
      PDF {id}

      {/* Glassmorphic Tooltip on Hover */}
      {isHovered && (
        <span
          className="absolute bottom-full left-1/2 z-50 mb-2 w-56 -translate-x-1/2 rounded-xl p-3 shadow-xl transition-all duration-200 border text-left flex flex-col pointer-events-none"
          style={{
            background: "rgba(30, 31, 34, 0.75)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            borderColor: "rgba(255, 255, 255, 0.12)",
            boxShadow: "0 8px 32px 0 rgba(0, 0, 0, 0.37)",
          }}
        >
          <span className="flex items-center gap-1.5">
            <span
              className="flex h-5 items-center justify-center rounded px-1.5 text-[8px] font-extrabold text-white"
              style={{ background: "var(--g-red)" }}
            >
              PDF
            </span>
          </span>
          <span className="mt-1.5 line-clamp-2 text-xs font-semibold text-white leading-normal">
            {citation?.paper_title || `Source Document ${id}`}
          </span>
          {citation?.section && (
            <span className="mt-1 text-[10px] text-neutral-300 truncate">
              {citation.section}
            </span>
          )}
        </span>
      )}
    </span>
  );
}

