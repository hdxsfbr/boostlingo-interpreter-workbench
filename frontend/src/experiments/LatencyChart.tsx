/** Simple SVG chart: headline H per turn (dots) per setup, with each setup's p50 as a line. */
import type { Turn } from "./api";

/** Series colours are CSS classes on tokens (--c-chart-1..6), never literals (A17). */
const series = (k: number) => `series-${(k % 6) + 1}`;

export function LatencyChart({ turns }: { turns: Turn[] }) {
  const setups = [...new Set(turns.map((t) => t.setup))];
  const pts = turns.filter((t) => t.h_ms != null);
  if (!pts.length) return <p className="empty">No latency samples yet.</p>;
  const W = 760, H = 220, P = 36;
  const maxN = Math.max(...turns.map((t) => t.n), 1);
  const maxH = Math.max(2500, ...pts.map((t) => t.h_ms!));
  const x = (n: number) => P + ((n - 1) / Math.max(1, maxN - 1)) * (W - 2 * P);
  const y = (ms: number) => H - P + 10 - (ms / maxH) * (H - 2 * P);
  const p50 = (s: string) => {
    const xs = pts.filter((t) => t.setup === s).map((t) => t.h_ms!).sort((a, b) => a - b);
    return xs.length ? xs[Math.floor((xs.length - 1) / 2)] : null;
  };
  return (
    <figure className="latency-chart" data-testid="latency-chart">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Headline latency per turn">
        {[0, 500, 1000, 1500, 2000, 2500].filter((v) => v <= maxH).map((v) => (
          <g key={v}>
            <line className="grid" x1={P} x2={W - P} y1={y(v)} y2={y(v)} />
            <text className="axis" x={4} y={y(v) + 4}>{v}</text>
          </g>
        ))}
        {setups.map((s, k) => {
          const m = p50(s);
          return (
            <g key={s}>
              {m != null && <line className={`p50 ${series(k)}`} x1={P} x2={W - P} y1={y(m)} y2={y(m)} strokeDasharray="4 3" />}
              {pts.filter((t) => t.setup === s).map((t) => (
                <circle key={`${s}-${t.n}`} className={`dot ${series(k)}`} cx={x(t.n)} cy={y(t.h_ms!)} r={3}>
                  <title>{`${s} #${t.n} ${t.utterance_id}: ${Math.round(t.h_ms!)} ms`}</title>
                </circle>
              ))}
            </g>
          );
        })}
        <text className="axis" x={W - P} y={H - 4} textAnchor="end">turn #</text>
      </svg>
      <figcaption>
        {setups.map((s, k) => (
          <span key={s} className="legend">
            <i className={series(k)} /> {s} (p50 {p50(s) != null ? Math.round(p50(s)!) : "–"} ms)
          </span>
        ))}
        <span className="hint"> H = last voiced frame → first audible sample (ms); dashed = p50.</span>
      </figcaption>
    </figure>
  );
}
