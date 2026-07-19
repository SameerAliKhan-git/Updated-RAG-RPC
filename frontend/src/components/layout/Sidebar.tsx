import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { NavLink, useNavigate, useParams } from "react-router-dom";
import { collectionsApi } from "../../api/collections";
import { useSessions } from "../../hooks/useSessions";
import { setActiveCollection, useActiveCollection } from "../../lib/activeCollection";
import { ThemeToggle } from "./ThemeToggle";

export function Sidebar({ onNavigate }: { onNavigate: () => void }) {
  const { sessions, remove } = useSessions();
  const navigate = useNavigate();
  const { sessionId: activeId } = useParams();

  return (
    <aside
      className="flex h-full w-72 flex-col px-3 py-4"
      style={{ background: "var(--surface)" }}
    >
      <div className="flex items-center justify-between px-2">
        <button
          onClick={() => {
            navigate("/");
            onNavigate();
          }}
          className="text-xl font-semibold gradient-text"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Corpus
        </button>
        <ThemeToggle />
      </div>

      <button
        onClick={() => {
          navigate("/");
          onNavigate();
        }}
        className="mt-5 flex items-center gap-2 self-start rounded-full px-4 py-2.5 text-sm font-medium transition-all hover:shadow-md"
        style={{ background: "var(--surface-2)", color: "var(--text)" }}
      >
        <PlusIcon /> New chat
      </button>

      <nav className="mt-5 flex flex-col gap-0.5">
        <SideLink to="/library" label="Library" icon={<BookIcon />} onNavigate={onNavigate} />
        <SideLink to="/research" label="Deep Research" icon={<FlaskIcon />} onNavigate={onNavigate} />
        <SideLink to="/galaxy" label="Galaxy" icon={<GalaxyIcon />} onNavigate={onNavigate} />
        <SideLink to="/system" label="System" icon={<PulseIcon />} onNavigate={onNavigate} />
      </nav>

      <CollectionsSection onNavigate={onNavigate} />

      <div className="mt-6 min-h-0 flex-1 overflow-y-auto">
        <p className="px-3 text-xs font-medium" style={{ color: "var(--text-tertiary)" }}>
          Recent
        </p>
        <ul className="mt-1.5 flex flex-col gap-0.5">
          {sessions.length === 0 && (
            <li className="px-3 py-2 text-sm" style={{ color: "var(--text-tertiary)" }}>
              No conversations yet
            </li>
          )}
          {sessions.map((s) => (
            <li key={s.id} className="group relative">
              <button
                onClick={() => {
                  navigate(`/chat/${s.id}`);
                  onNavigate();
                }}
                className="w-full truncate rounded-full px-3 py-2 pr-8 text-left text-sm transition-colors"
                style={{
                  background: s.id === activeId ? "var(--accent-soft)" : "transparent",
                  color: s.id === activeId ? "var(--accent)" : "var(--text-secondary)",
                }}
              >
                {s.title}
              </button>
              <button
                aria-label="Delete session"
                onClick={() => remove(s.id)}
                className="absolute right-2 top-1/2 hidden -translate-y-1/2 rounded-full p-1 group-hover:block"
                style={{ color: "var(--text-tertiary)" }}
              >
                <XIcon />
              </button>
            </li>
          ))}
        </ul>
      </div>

      <p className="px-3 pt-3 text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
        Every answer cited to its source.
      </p>
    </aside>
  );
}

function CollectionsSection({ onNavigate }: { onNavigate: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const active = useActiveCollection();
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  const { data } = useQuery({ queryKey: ["collections"], queryFn: collectionsApi.list, staleTime: 15_000 });
  const collections = data?.collections ?? [];

  const create = async () => {
    const name = newName.trim();
    if (!name) return;
    try {
      const created = await collectionsApi.create(name);
      setNewName("");
      setCreating(false);
      void queryClient.invalidateQueries({ queryKey: ["collections"] });
      setActiveCollection({ id: created.id, name: created.name });
      navigate("/");
      onNavigate();
    } catch {
      setCreating(false);
    }
  };

  return (
    <div className="mt-5">
      <div className="flex items-center justify-between px-3">
        <p className="text-xs font-medium" style={{ color: "var(--text-tertiary)" }}>
          Collections
        </p>
        <button
          aria-label="New collection"
          onClick={() => setCreating((c) => !c)}
          className="rounded-full px-1.5 text-sm"
          style={{ color: "var(--text-tertiary)" }}
        >
          +
        </button>
      </div>
      {creating && (
        <div className="mt-1 px-3">
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void create();
              if (e.key === "Escape") setCreating(false);
            }}
            placeholder="Collection name…"
            className="w-full rounded-full px-3 py-1.5 text-xs outline-none"
            style={{ background: "var(--surface-2)", color: "var(--text)" }}
          />
        </div>
      )}
      <ul className="mt-1 flex max-h-44 flex-col gap-0.5 overflow-y-auto">
        {collections.map((c) => {
          const isActive = active?.id === c.id;
          return (
            <li key={c.id} className="group relative">
              <button
                onClick={() => {
                  setActiveCollection(isActive ? null : { id: c.id, name: c.name });
                  navigate("/");
                  onNavigate();
                }}
                className="flex w-full items-center justify-between rounded-full px-3 py-1.5 pr-8 text-left text-sm transition-colors"
                style={{
                  background: isActive ? "var(--accent-soft)" : "transparent",
                  color: isActive ? "var(--accent)" : "var(--text-secondary)",
                }}
              >
                <span className="truncate">{c.name}</span>
                <span className="ml-2 text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                  {c.paper_count}
                </span>
              </button>
              {c.paper_count > 0 && <AudioOverviewButton collectionId={c.id} />}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function AudioOverviewButton({ collectionId }: { collectionId: string }) {
  const [state, setState] = useState<"idle" | "generating" | "playing">("idle");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const pollRef = useRef(0);

  const play = () => {
    const audio = new Audio(`/api/v1/collections/${collectionId}/audio`);
    audioRef.current = audio;
    audio.onended = () => setState("idle");
    void audio.play();
    setState("playing");
  };

  const onClick = async () => {
    if (state === "playing") {
      audioRef.current?.pause();
      setState("idle");
      return;
    }
    const status = await fetch(`/api/v1/collections/${collectionId}/audio/status`).then((r) => r.json());
    if (status.file_exists) {
      play();
      return;
    }
    setState("generating");
    await fetch(`/api/v1/collections/${collectionId}/audio`, { method: "POST" });
    pollRef.current = window.setInterval(async () => {
      const s = await fetch(`/api/v1/collections/${collectionId}/audio/status`).then((r) => r.json());
      if (s.status === "done" && s.file_exists) {
        clearInterval(pollRef.current);
        play();
      } else if (s.status === "failed") {
        clearInterval(pollRef.current);
        setState("idle");
      }
    }, 4000);
  };

  return (
    <button
      aria-label="Audio overview"
      title={state === "generating" ? "Generating audio overview…" : "Play audio overview"}
      onClick={() => void onClick()}
      className={`absolute right-1.5 top-1/2 -translate-y-1/2 rounded-full p-1 transition-opacity ${
        state === "idle" ? "opacity-0 group-hover:opacity-100" : "opacity-100"
      }`}
      style={{ color: state === "playing" ? "var(--accent)" : "var(--text-tertiary)" }}
    >
      {state === "generating" ? (
        <span className="gradient-shimmer text-[10px] font-bold">…</span>
      ) : (
        <HeadphonesIcon />
      )}
    </button>
  );
}

function HeadphonesIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 18v-6a9 9 0 0 1 18 0v6" />
      <path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z" />
    </svg>
  );
}

function SideLink({
  to,
  label,
  icon,
  onNavigate,
}: {
  to: string;
  label: string;
  icon: React.ReactNode;
  onNavigate: () => void;
}) {
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      className="flex items-center gap-3 rounded-full px-3 py-2 text-sm transition-colors"
      style={({ isActive }) => ({
        background: isActive ? "var(--accent-soft)" : "transparent",
        color: isActive ? "var(--accent)" : "var(--text-secondary)",
      })}
    >
      {icon}
      {label}
    </NavLink>
  );
}

const iconProps = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

function PlusIcon() {
  return (
    <svg {...iconProps}>
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

function BookIcon() {
  return (
    <svg {...iconProps}>
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </svg>
  );
}

function FlaskIcon() {
  return (
    <svg {...iconProps}>
      <path d="M10 2v6L4.5 18a2 2 0 0 0 1.8 3h11.4a2 2 0 0 0 1.8-3L14 8V2" />
      <line x1="8" y1="2" x2="16" y2="2" />
      <line x1="7" y1="14" x2="17" y2="14" />
    </svg>
  );
}

function GalaxyIcon() {
  return (
    <svg {...iconProps}>
      <circle cx="12" cy="12" r="2.5" />
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" transform="rotate(60 12 12)" />
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" transform="rotate(-60 12 12)" />
    </svg>
  );
}

function PulseIcon() {
  return (
    <svg {...iconProps}>
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
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
