import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { API_BASE } from "../../api/client";

interface BuildStatus {
  status: "idle" | "running" | "done" | "error" | "already_running";
  stats?: { papers: number; entities: number; edges: number; errors: number };
  error?: string;
}

interface GraphNode {
  id: string;
  name: string;
  type: string;
  mentions: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
}
interface GraphEdge {
  source: string;
  target: string;
  relation: string;
}

const TYPE_COLORS: Record<string, string> = {
  method: "var(--g-blue)",
  dataset: "var(--g-green)",
  task: "#9b72cb",
  metric: "var(--g-yellow)",
};

const W = 900;
const H = 620;

async function fetchGraph(): Promise<{ nodes: GraphNode[]; edges: GraphEdge[] }> {
  const res = await fetch(`${API_BASE}/concepts/graph?limit=100`);
  if (!res.ok) throw new Error(`${res.status}`);
  const data = await res.json();
  return {
    nodes: data.nodes.map((n: Omit<GraphNode, "x" | "y" | "vx" | "vy">, i: number) => ({
      ...n,
      x: W / 2 + Math.cos((i / data.nodes.length) * Math.PI * 2) * 220,
      y: H / 2 + Math.sin((i / data.nodes.length) * Math.PI * 2) * 200,
      vx: 0,
      vy: 0,
    })),
    edges: data.edges,
  };
}

/** Minimal force simulation — repulsion + edge springs + center gravity. */
function useForceLayout(nodes: GraphNode[], edges: GraphEdge[]) {
  const [, setTick] = useState(0);
  const frame = useRef(0);

  useEffect(() => {
    if (nodes.length === 0) return;
    const byId = new Map(nodes.map((n) => [n.id, n]));
    let iterations = 0;

    const step = () => {
      iterations++;
      for (const a of nodes) {
        for (const b of nodes) {
          if (a === b) continue;
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d2 = Math.max(dx * dx + dy * dy, 40);
          const f = 1400 / d2;
          const d = Math.sqrt(d2);
          a.vx += (dx / d) * f;
          a.vy += (dy / d) * f;
        }
        a.vx += (W / 2 - a.x) * 0.002;
        a.vy += (H / 2 - a.y) * 0.002;
      }
      for (const e of edges) {
        const s = byId.get(e.source);
        const t = byId.get(e.target);
        if (!s || !t) continue;
        const dx = t.x - s.x;
        const dy = t.y - s.y;
        const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const f = (d - 110) * 0.004;
        s.vx += (dx / d) * f;
        s.vy += (dy / d) * f;
        t.vx -= (dx / d) * f;
        t.vy -= (dy / d) * f;
      }
      for (const n of nodes) {
        n.x = Math.max(30, Math.min(W - 30, n.x + n.vx));
        n.y = Math.max(24, Math.min(H - 24, n.y + n.vy));
        n.vx *= 0.82;
        n.vy *= 0.82;
      }
      setTick((t) => t + 1);
      if (iterations < 260) frame.current = requestAnimationFrame(step);
    };

    frame.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame.current);
  }, [nodes, edges]);
}

export function GalaxyView() {
  const navigate = useNavigate();
  const [hovered, setHovered] = useState<GraphNode | null>(null);
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["conceptGraph"], queryFn: fetchGraph });

  const [build, setBuild] = useState<BuildStatus | null>(null);
  const pollRef = useRef<number>(0);

  const startBuild = async () => {
    const res = await fetch(`${API_BASE}/concepts/build`, { method: "POST" });
    if (!res.ok) return;
    setBuild((await res.json()) as BuildStatus);
  };

  useEffect(() => {
    if (!build || build.status === "done" || build.status === "error") return;
    pollRef.current = window.setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/concepts/build/status`);
        if (!res.ok) return;
        const next = (await res.json()) as BuildStatus;
        setBuild(next);
        if (next.status === "done") void refetch();
      } catch {
        // transient poll failure — keep trying
      }
    }, 3000);
    return () => clearInterval(pollRef.current);
  }, [build?.status, refetch]);

  const building = build && (build.status === "running" || build.status === "already_running");

  const nodes = useMemo(() => data?.nodes ?? [], [data]);
  const edges = useMemo(() => data?.edges ?? [], [data]);
  useForceLayout(nodes, edges);

  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const maxMentions = Math.max(1, ...nodes.map((n) => n.mentions));

  return (
    <div className="flex h-full flex-col overflow-hidden px-4 py-6 md:px-8">
      <div className="mx-auto flex w-full max-w-5xl items-start justify-between">
        <div>
          <h1 className="gradient-text text-2xl font-semibold" style={{ fontFamily: "var(--font-display)" }}>
            Research Galaxy
          </h1>
          <p className="mt-1 text-sm" style={{ color: "var(--text-tertiary)" }}>
            Concepts extracted nightly from your corpus — click one to explore its papers
          </p>
        </div>
        <div className="flex flex-wrap gap-3 pt-2">
          {Object.entries(TYPE_COLORS).map(([type, color]) => (
            <span key={type} className="inline-flex items-center gap-1.5 text-[11px] capitalize" style={{ color: "var(--text-secondary)" }}>
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />
              {type}
            </span>
          ))}
        </div>
      </div>

      <div className="mx-auto mt-4 w-full max-w-5xl min-h-0 flex-1 overflow-hidden rounded-3xl" style={{ background: "var(--surface)" }}>
        {isLoading && <p className="gradient-shimmer p-8 text-center text-sm font-medium">Charting the galaxy…</p>}
        {error != null && (
          <p className="p-8 text-center text-sm" style={{ color: "var(--g-red)" }}>
            Could not load the concept graph.
          </p>
        )}
        {data && nodes.length === 0 && (
          <div className="flex flex-col items-center gap-3 p-8 text-center text-sm" style={{ color: "var(--text-tertiary)" }}>
            <p>
              No concepts extracted yet. This populates from the nightly Airflow graph builder — or
              build it now without waiting for the schedule or the airflow profile.
            </p>
            {build?.status === "error" && (
              <p style={{ color: "var(--g-red)" }}>Build failed: {build.error ?? "unknown error"}</p>
            )}
            {build?.status === "done" && build.stats && (
              <p style={{ color: "var(--text-secondary)" }}>
                Processed {build.stats.papers} paper{build.stats.papers === 1 ? "" : "s"}, found{" "}
                {build.stats.entities} concepts — reloading…
              </p>
            )}
            <button
              onClick={() => void startBuild()}
              disabled={!!building}
              className="rounded-full px-5 py-2 text-sm font-medium text-white disabled:opacity-40"
              style={{ background: "var(--gradient-gemini-solid)" }}
            >
              {building ? "Building…" : "Build now"}
            </button>
            <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
              Needs papers already ingested. One fast-LLM call per paper — may take a few minutes on CPU.
            </p>
          </div>
        )}
        {nodes.length > 0 && (
          <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full">
            {edges.map((e, i) => {
              const s = byId.get(e.source);
              const t = byId.get(e.target);
              if (!s || !t) return null;
              const active = hovered && (hovered.id === e.source || hovered.id === e.target);
              return (
                <line
                  key={i}
                  x1={s.x}
                  y1={s.y}
                  x2={t.x}
                  y2={t.y}
                  stroke={active ? "var(--accent)" : "var(--surface-3)"}
                  strokeWidth={active ? 1.6 : 0.8}
                  opacity={hovered && !active ? 0.25 : 0.8}
                />
              );
            })}
            {nodes.map((n) => {
              const r = 5 + (n.mentions / maxMentions) * 14;
              const dim = hovered !== null && hovered.id !== n.id;
              return (
                <g
                  key={n.id}
                  transform={`translate(${n.x},${n.y})`}
                  className="cursor-pointer"
                  opacity={dim ? 0.35 : 1}
                  onMouseEnter={() => setHovered(n)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => navigate(`/?q=${encodeURIComponent(`What does my corpus say about ${n.name}?`)}`)}
                >
                  <circle r={r} fill={TYPE_COLORS[n.type] ?? "var(--text-tertiary)"} opacity={0.85} />
                  {(r > 10 || hovered?.id === n.id) && (
                    <text
                      y={-r - 5}
                      textAnchor="middle"
                      fontSize="10"
                      fill="var(--text-secondary)"
                      style={{ pointerEvents: "none" }}
                    >
                      {n.name.length > 26 ? `${n.name.slice(0, 26)}…` : n.name}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        )}
      </div>

      {hovered && (
        <p className="mx-auto mt-2 w-full max-w-5xl text-center text-xs" style={{ color: "var(--text-tertiary)" }}>
          <span className="capitalize">{hovered.type}</span> · mentioned in {hovered.mentions} paper
          {hovered.mentions === 1 ? "" : "s"} · click to ask about it
        </p>
      )}
    </div>
  );
}
