import { useState } from "react";
import type { EvalHistoryEntry } from "../../api/types";

// Palette validated with the dataviz six-checks (blue/green pass CVD + normal-vision
// separation on both surfaces; light-mode contrast WARN relieved by direct labels
// and the table view below).
const SERIES = [
  { key: "faithfulness" as const, label: "Faithfulness", color: "#4285F4" },
  { key: "answer_relevancy" as const, label: "Answer relevancy", color: "#34A853" },
];

const W = 560;
const H = 180;
const PAD = { top: 12, right: 110, bottom: 24, left: 36 };

export function EvalTrendChart({ history }: { history: EvalHistoryEntry[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);

  // History arrives newest-first; plot oldest → newest
  const points = [...history].reverse();
  if (points.length === 0) {
    return (
      <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
        No evaluation history yet — run a golden evaluation to start the trend.
      </p>
    );
  }

  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (points.length === 1 ? plotW / 2 : (i / (points.length - 1)) * plotW);
  const y = (v: number) => PAD.top + (1 - Math.max(0, Math.min(1, v))) * plotH;

  const fmtDate = (ts: number) =>
    new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });

  return (
    <div>
      <div className="flex items-center gap-4">
        {/* Legend — identity never by color alone (labels repeat at line ends) */}
        {SERIES.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5 text-[11px]" style={{ color: "var(--text-secondary)" }}>
            <span className="inline-block h-0.5 w-4 rounded-full" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
        <button
          onClick={() => setShowTable((t) => !t)}
          className="ml-auto rounded-full px-3 py-1 text-[11px] font-medium"
          style={{ background: "var(--surface-2)", color: "var(--text-secondary)" }}
        >
          {showTable ? "Chart" : "Table"}
        </button>
      </div>

      {showTable ? (
        <table className="mt-3 w-full text-[12px]" style={{ color: "var(--text-secondary)" }}>
          <thead>
            <tr style={{ color: "var(--text-tertiary)" }}>
              <th className="py-1 text-left font-medium">Run</th>
              <th className="py-1 text-right font-medium">Faithfulness</th>
              <th className="py-1 text-right font-medium">Answer relevancy</th>
              <th className="py-1 text-right font-medium">Samples</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p, i) => (
              <tr key={i} style={{ borderTop: "1px solid var(--border)" }}>
                <td className="py-1">{fmtDate(p.timestamp)}</td>
                <td className="py-1 text-right">{p.faithfulness.toFixed(2)}</td>
                <td className="py-1 text-right">{p.answer_relevancy.toFixed(2)}</td>
                <td className="py-1 text-right">{p.sample_count ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="mt-2 w-full"
          role="img"
          aria-label="Evaluation score trend over recent runs"
          onMouseLeave={() => setHover(null)}
        >
          {/* Recessive grid + axis labels in text tokens */}
          {[0, 0.5, 1].map((v) => (
            <g key={v}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y(v)}
                y2={y(v)}
                stroke="var(--border)"
                strokeWidth="1"
                strokeDasharray={v === 0 ? undefined : "2 4"}
              />
              <text x={PAD.left - 6} y={y(v) + 3} textAnchor="end" fontSize="9" fill="var(--text-tertiary)">
                {v.toFixed(1)}
              </text>
            </g>
          ))}

          {SERIES.map((s) => {
            const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(p[s.key] ?? 0)}`).join(" ");
            const last = points[points.length - 1];
            return (
              <g key={s.key}>
                <path d={path} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" />
                {/* Direct label at line end — text token ink, colored dot carries identity */}
                <circle cx={x(points.length - 1)} cy={y(last[s.key] ?? 0)} r="3" fill={s.color} />
                <text
                  x={x(points.length - 1) + 8}
                  y={y(last[s.key] ?? 0) + 3}
                  fontSize="10"
                  fill="var(--text-secondary)"
                >
                  {s.label} {(last[s.key] ?? 0).toFixed(2)}
                </text>
              </g>
            );
          })}

          {/* Hover layer: wide hit targets + tooltip */}
          {points.map((_, i) => (
            <rect
              key={i}
              x={x(i) - plotW / Math.max(1, points.length - 1) / 2}
              y={PAD.top}
              width={plotW / Math.max(1, points.length - 1)}
              height={plotH}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
            />
          ))}
          {hover !== null && (
            <g pointerEvents="none">
              <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={H - PAD.bottom} stroke="var(--text-tertiary)" strokeWidth="1" strokeDasharray="3 3" />
              {SERIES.map((s) => (
                <circle key={s.key} cx={x(hover)} cy={y(points[hover][s.key] ?? 0)} r="4" fill={s.color} stroke="var(--bg)" strokeWidth="2" />
              ))}
              <g transform={`translate(${Math.min(x(hover) + 8, W - PAD.right - 120)}, ${PAD.top + 4})`}>
                <rect width="118" height="46" rx="8" fill="var(--surface-2)" stroke="var(--border)" />
                <text x="8" y="14" fontSize="9" fill="var(--text-tertiary)">
                  {fmtDate(points[hover].timestamp)} · {points[hover].sample_count ?? "?"} samples
                </text>
                <text x="8" y="27" fontSize="10" fill="var(--text)">
                  Faithfulness {(points[hover].faithfulness ?? 0).toFixed(2)}
                </text>
                <text x="8" y="40" fontSize="10" fill="var(--text)">
                  Relevancy {(points[hover].answer_relevancy ?? 0).toFixed(2)}
                </text>
              </g>
            </g>
          )}
        </svg>
      )}
    </div>
  );
}
