import { useState, type ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { BottomNav } from "./BottomNav";

export function AppShell({ children }: { children: ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="flex h-full" style={{ background: "var(--bg)" }}>
      {/* Desktop sidebar */}
      <div className="hidden md:block">
        <Sidebar onNavigate={() => undefined} />
      </div>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0"
            style={{ background: "var(--scrim)" }}
            onClick={() => setDrawerOpen(false)}
          />
          <div className="absolute inset-y-0 left-0">
            <Sidebar onNavigate={() => setDrawerOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar */}
        <header
          className="flex items-center gap-3 px-4 py-3 md:hidden"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <button
            aria-label="Open menu"
            onClick={() => setDrawerOpen(true)}
            className="rounded-full p-2 transition-colors"
            style={{ color: "var(--text-secondary)" }}
          >
            <MenuIcon />
          </button>
          <span className="font-display text-lg font-semibold gradient-text" style={{ fontFamily: "var(--font-display)" }}>
            Corpus
          </span>
        </header>

        <main className="min-h-0 flex-1 overflow-hidden pb-14 md:pb-0">{children}</main>
        <BottomNav />
      </div>
    </div>
  );
}

function MenuIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <line x1="4" y1="7" x2="20" y2="7" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="17" x2="20" y2="17" />
    </svg>
  );
}
