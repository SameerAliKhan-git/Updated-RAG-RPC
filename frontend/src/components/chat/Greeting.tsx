import { motion } from "framer-motion";

const SUGGESTIONS = [
  "What is scaled dot-product attention?",
  "Compare state space models with transformers",
  "What are the latest advances in retrieval-augmented generation?",
  "Explain LoRA fine-tuning and its trade-offs",
];

export function Greeting({ onSuggestion }: { onSuggestion: (q: string) => void }) {
  return (
    <div className="relative flex min-h-0 flex-1 flex-col items-center justify-center overflow-hidden px-6">
      {/* Ethereal blurred gradient blobs */}
      <div className="gemini-blob left-[15%] top-[20%] h-72 w-72" style={{ background: "var(--g-blue)" }} />
      <div className="gemini-blob bottom-[15%] right-[12%] h-80 w-80" style={{ background: "#9b72cb" }} />

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1] }}
        className="relative z-10 text-center"
      >
        <h1
          className="gradient-text text-4xl font-medium md:text-5xl"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Hello, researcher
        </h1>
        <p className="mt-3 text-lg" style={{ color: "var(--text-tertiary)" }}>
          Ask anything about your paper corpus — every answer cited.
        </p>
      </motion.div>

      <motion.div
        className="relative z-10 mt-10 grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2"
        initial="hidden"
        animate="show"
        variants={{ show: { transition: { staggerChildren: 0.08, delayChildren: 0.25 } } }}
      >
        {SUGGESTIONS.map((s) => (
          <motion.button
            key={s}
            variants={{ hidden: { opacity: 0, y: 10 }, show: { opacity: 1, y: 0 } }}
            onClick={() => onSuggestion(s)}
            className="rounded-3xl px-5 py-4 text-left text-sm transition-all hover:-translate-y-0.5 hover:shadow-lg"
            style={{ background: "var(--surface)", color: "var(--text-secondary)" }}
          >
            {s}
          </motion.button>
        ))}
      </motion.div>
    </div>
  );
}
