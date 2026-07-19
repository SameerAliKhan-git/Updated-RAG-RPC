import { useCallback, useRef, useState } from "react";
import { useSpeechInput } from "../../hooks/useSpeechInput";

export interface Attachment {
  arxivId: string;
  title: string;
  status: "uploading" | "ready" | "error";
}

export function PromptBar({
  onSend,
  disabled,
  centered,
  attachment,
  onAttach,
  onRemoveAttachment,
  deepVerify = false,
  onToggleDeepVerify,
  visualOnly = false,
  onToggleVisualOnly,
}: {
  onSend: (query: string) => void;
  disabled: boolean;
  centered: boolean;
  attachment?: Attachment | null;
  onAttach?: (file: File) => void;
  onRemoveAttachment?: () => void;
  deepVerify?: boolean;
  onToggleDeepVerify?: () => void;
  visualOnly?: boolean;
  onToggleVisualOnly?: () => void;
}) {
  const [value, setValue] = useState("");
  const [rippleKey, setRippleKey] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const onSpeech = useCallback((text: string) => {
    setValue((v) => (v ? `${v} ${text}` : text));
  }, []);
  const speech = useSpeechInput(onSpeech);

  const displayValue = speech.interim ? `${value}${value ? " " : ""}${speech.interim}` : value;
  const multiline = displayValue.includes("\n") || displayValue.length > 90;

  const submit = () => {
    const query = value.trim();
    if (!query || disabled || attachment?.status === "uploading") return;
    setRippleKey((k) => k + 1);
    onSend(query);
    setValue("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  return (
    <div className={`w-full px-4 pb-5 ${centered ? "md:pb-24" : ""}`}>
      {/* Attachment chip — Gemini-style card above the input */}
      {attachment && (
        <div className="mx-auto mb-2 flex max-w-3xl">
          <div
            className="flex items-center gap-2.5 rounded-2xl px-3.5 py-2"
            style={{ background: "var(--surface-2)" }}
          >
            <span
              className="flex h-7 w-7 items-center justify-center rounded-lg text-[8px] font-bold text-white"
              style={{ background: "var(--g-red)" }}
            >
              PDF
            </span>
            <div className="min-w-0">
              <p className="max-w-56 truncate text-xs font-medium" style={{ color: "var(--text)" }}>
                {attachment.title}
              </p>
              <p className="text-[10px]" style={{ color: attachment.status === "error" ? "var(--g-red)" : "var(--text-tertiary)" }}>
                {attachment.status === "uploading" && <span className="gradient-shimmer">Parsing & indexing…</span>}
                {attachment.status === "ready" && "Ready — answers will use this document"}
                {attachment.status === "error" && "Upload failed"}
              </p>
            </div>
            <button
              aria-label="Remove attachment"
              onClick={onRemoveAttachment}
              className="ml-1 rounded-full p-1"
              style={{ color: "var(--text-tertiary)" }}
            >
              <XIcon />
            </button>
          </div>
        </div>
      )}

      <div
        className="mx-auto flex max-w-3xl items-end gap-1.5 px-4 py-3 transition-all"
        style={{
          background: "var(--surface)",
          borderRadius: multiline ? "28px" : "var(--radius-pill)",
          boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
        }}
      >
        {onAttach && (
          <>
            <button
              aria-label="Attach a PDF"
              title="Attach a PDF — ask questions about it"
              onClick={() => fileRef.current?.click()}
              disabled={disabled || attachment?.status === "uploading"}
              className="shrink-0 rounded-full p-2 transition-colors hover:opacity-75 disabled:opacity-40"
              style={{ color: "var(--text-secondary)" }}
            >
              <PaperclipIcon />
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onAttach(f);
                e.target.value = "";
              }}
            />
          </>
        )}

        <textarea
          ref={textareaRef}
          value={displayValue}
          rows={1}
          placeholder={attachment?.status === "ready" ? `Ask about ${attachment.title}…` : "Ask Corpus…"}
          disabled={disabled}
          onChange={(e) => {
            setValue(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          className="max-h-40 flex-1 resize-none bg-transparent py-1 text-[15px] outline-none"
          style={{ color: "var(--text)" }}
        />
        {onToggleVisualOnly && (
          <button
            aria-label="Search only tables and figures"
            title="Tables & figures only: restrict retrieval to tables and figure captions"
            onClick={onToggleVisualOnly}
            className="shrink-0 rounded-full px-2.5 py-2 text-[10px] font-semibold transition-all"
            style={{
              background: visualOnly ? "var(--accent-soft)" : "transparent",
              color: visualOnly ? "var(--accent)" : "var(--text-tertiary)",
            }}
          >
            <TableIcon />
          </button>
        )}

        {speech.supported && (
          <button
            aria-label={speech.listening ? "Stop voice input" : "Start voice input"}
            title="Voice input"
            onClick={() => (speech.listening ? speech.stop() : speech.start())}
            className="shrink-0 rounded-full p-2 transition-all"
            style={{
              background: speech.listening ? "var(--accent-soft)" : "transparent",
              color: speech.listening ? "var(--g-red)" : "var(--text-tertiary)",
            }}
          >
            <MicIcon />
          </button>
        )}

        {onToggleDeepVerify && (
          <button
            aria-label="Toggle deep verification"
            title="Deep verify: LLM checks every claim against its source (slower)"
            onClick={onToggleDeepVerify}
            className="shrink-0 rounded-full px-2.5 py-2 text-[10px] font-semibold transition-all"
            style={{
              background: deepVerify ? "var(--accent-soft)" : "transparent",
              color: deepVerify ? "var(--accent)" : "var(--text-tertiary)",
            }}
          >
            <ShieldIcon filled={deepVerify} />
          </button>
        )}

        <button
          aria-label="Send"
          onClick={submit}
          disabled={disabled || !value.trim() || attachment?.status === "uploading"}
          className="relative shrink-0 overflow-visible rounded-full p-2.5 transition-all disabled:opacity-35"
          style={{
            background: value.trim() ? "var(--gradient-gemini-solid)" : "var(--surface-3)",
            color: value.trim() ? "#fff" : "var(--text-tertiary)",
          }}
        >
          {rippleKey > 0 && (
            <span
              key={rippleKey}
              className="animate-ripple absolute inset-0 rounded-full"
              style={{ background: "var(--g-blue)" }}
            />
          )}
          <SendIcon />
        </button>
      </div>
      <p className="mx-auto mt-2 max-w-3xl text-center text-[11px]" style={{ color: "var(--text-tertiary)" }}>
        {deepVerify
          ? "Deep verify on — every claim will be checked against its source (slower)."
          : "Corpus answers only from indexed papers and cites every claim."}
      </p>
    </div>
  );
}

function SendIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" className="relative z-10">
      <path d="M3.4 20.4l17.45-7.48a1 1 0 0 0 0-1.84L3.4 3.6a.993.993 0 0 0-1.39.91L2 9.12c0 .5.37.93.87.99L17 12 2.87 13.88c-.5.07-.87.5-.87 1l.01 4.61c0 .71.73 1.2 1.39.91z" />
    </svg>
  );
}

function PaperclipIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  );
}

function XIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  );
}

function TableIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <line x1="3" y1="9" x2="21" y2="9" />
      <line x1="3" y1="15" x2="21" y2="15" />
      <line x1="12" y1="3" x2="12" y2="21" />
    </svg>
  );
}

function ShieldIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      {filled && <polyline points="9 12 11 14 15 10" stroke="var(--accent-soft)" fill="none" />}
    </svg>
  );
}
