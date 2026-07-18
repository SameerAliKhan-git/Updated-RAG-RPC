import { useState } from "react";
import { api } from "../../api/client";

export function FeedbackBar({ sessionId }: { sessionId: string | null }) {
  const [sent, setSent] = useState<"up" | "down" | null>(null);
  const [showCorrection, setShowCorrection] = useState(false);
  const [correction, setCorrection] = useState("");

  const send = async (rating: "up" | "down", text?: string) => {
    setSent(rating);
    try {
      await api.sendFeedback(sessionId ?? "anonymous", rating, text);
    } catch {
      // Feedback is fire-and-forget
    }
  };

  return (
    <span className="inline-flex items-center gap-1.5">
      <button
        aria-label="Good answer"
        disabled={sent !== null}
        onClick={() => void send("up")}
        className="rounded-full p-1.5 transition-colors disabled:opacity-100"
        style={{ color: sent === "up" ? "var(--g-green)" : "var(--text-tertiary)" }}
      >
        <ThumbIcon />
      </button>
      <button
        aria-label="Bad answer"
        disabled={sent !== null}
        onClick={() => {
          setShowCorrection(true);
        }}
        className="rounded-full p-1.5 transition-colors disabled:opacity-100"
        style={{ color: sent === "down" ? "var(--g-red)" : "var(--text-tertiary)", transform: "scaleY(-1)" }}
      >
        <ThumbIcon />
      </button>

      {showCorrection && sent === null && (
        <span className="inline-flex items-center gap-1.5">
          <input
            value={correction}
            onChange={(e) => setCorrection(e.target.value)}
            placeholder="What was wrong? (optional)"
            className="rounded-full px-3 py-1 text-xs outline-none"
            style={{ background: "var(--surface)", color: "var(--text)" }}
          />
          <button
            onClick={() => void send("down", correction)}
            className="rounded-full px-3 py-1 text-xs font-medium"
            style={{ background: "var(--surface-2)", color: "var(--text-secondary)" }}
          >
            Send
          </button>
        </span>
      )}
      {sent && (
        <span className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
          Thanks for the feedback
        </span>
      )}
    </span>
  );
}

function ThumbIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" />
    </svg>
  );
}
