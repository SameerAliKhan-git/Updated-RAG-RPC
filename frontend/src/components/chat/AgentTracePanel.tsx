import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";

export function AgentTracePanel({ traces, active }: { traces: string[]; active: boolean }) {
  const [open, setOpen] = useState(true);
  if (traces.length === 0) return null;

  return (
    <div className="rounded-3xl px-5 py-4" style={{ background: "var(--surface)" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 text-sm font-medium"
        style={{ color: "var(--text-secondary)" }}
      >
        <span className={active ? "gradient-shimmer" : ""}>
          {active ? "Thinking" : "Reasoning steps"}
        </span>
        <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
          {traces.length} step{traces.length === 1 ? "" : "s"}
        </span>
        <ChevronIcon open={open} />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.ol
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.2, 0.8, 0.2, 1] }}
            className="mt-3 flex flex-col gap-2 overflow-hidden"
          >
            {traces.map((step, i) => {
              const isLast = i === traces.length - 1;
              return (
                <motion.li
                  key={i}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.3, delay: 0.03 }}
                  className="flex items-start gap-2.5 text-[13px]"
                  style={{ color: isLast && active ? "var(--text)" : "var(--text-tertiary)" }}
                >
                  <span
                    className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                    style={{
                      background: isLast && active ? "var(--gradient-gemini-solid)" : "var(--surface-3)",
                    }}
                  />
                  {step}
                </motion.li>
              );
            })}
          </motion.ol>
        )}
      </AnimatePresence>
    </div>
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="ml-auto transition-transform"
      style={{ transform: open ? "rotate(180deg)" : "none" }}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}
