import { NavLink } from "react-router-dom";

const items = [
  { to: "/", label: "Ask" },
  { to: "/library", label: "Library" },
  { to: "/system", label: "System" },
];

export function BottomNav() {
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-30 flex justify-around py-2 md:hidden"
      style={{ background: "var(--surface)", borderTop: "1px solid var(--border)" }}
    >
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          className="rounded-full px-5 py-1.5 text-xs font-medium transition-colors"
          style={({ isActive }) => ({
            background: isActive ? "var(--accent-soft)" : "transparent",
            color: isActive ? "var(--accent)" : "var(--text-tertiary)",
          })}
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}
