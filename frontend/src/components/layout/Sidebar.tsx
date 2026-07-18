import { NavLink, useNavigate, useParams } from "react-router-dom";
import { useSessions } from "../../hooks/useSessions";
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
        <SideLink to="/system" label="System" icon={<PulseIcon />} onNavigate={onNavigate} />
      </nav>

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
