import type { Mode } from "../session/protocol";
import { LIMIT_MS, summarize, TARGET_MS, toCsv, toRecord } from "../store/metrics";
import type { State } from "../store/reducer";
import { LatencyWaterfall } from "./LatencyWaterfall";

const fmt = (v?: number) => (v === undefined ? "—" : `${Math.round(v)}`);

function download(name: string, body: string, type: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([body], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function MetricsSummary({ state }: { state: State }) {
  const turns = Object.values(state.turns);
  const last = [...turns].reverse().find((t) => t.browserMarks.commit_sent !== undefined && t.mode === state.mode)
    ?? [...turns].reverse().find((t) => t.browserMarks.commit_sent !== undefined);
  const cur = summarize(turns, state.mode);
  const verdict = (v?: number) => (v === undefined ? "" : v <= TARGET_MS[state.mode] ? "ok" : v <= LIMIT_MS[state.mode] ? "warn" : "bad");
  const fmtK = (v?: number) => (v === undefined ? "—" : Math.round(v).toLocaleString("en-US"));
  const exp = (kind: "json" | "csv") => {
    const recs = turns.map(toRecord);
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    if (kind === "json") download(`turns-${stamp}.json`, JSON.stringify(recs, null, 2), "application/json");
    else download(`turns-${stamp}.csv`, toCsv(recs), "text/csv");
  };
  return (
    <aside className="card metrics" data-testid="metrics" aria-label="Latency">
      <h2 className="card-title">Latency · last turn</h2>
      {last ? <LatencyWaterfall turn={last} /> : <p className="empty">No timed turn yet.</p>}
      <div className="stats">
        <div className="stat"><span>turns</span><b>{cur.headline.n}</b></div>
        <div className="stat"><span>p50</span><b className={verdict(cur.headline.median)}>{fmtK(cur.headline.median)}</b></div>
        <div className="stat"><span>p90</span><b className={verdict(cur.headline.p90)}>{fmtK(cur.headline.p90)}</b></div>
      </div>
      <h2 className="card-title sub">All turns (speech end → first audio)</h2>
      {(["cascade", "realtime"] as Mode[]).map((m) => {
        const s = summarize(turns, m);
        return (
          <div key={m} className="mode-stats">
            <h3>{m} <small>target {TARGET_MS[m]} ms · limit {LIMIT_MS[m]} ms</small></h3>
            <table>
              <thead><tr><th /><th>n</th><th>p50</th><th>p90</th></tr></thead>
              <tbody>
                <tr className="headline"><td>headline</td><td>{s.headline.n}</td><td>{fmt(s.headline.median)}</td><td>{fmt(s.headline.p90)}</td></tr>
                {Object.entries(s.stages).map(([k, v]) => (
                  <tr key={k}><td>{k}*</td><td>{v.n}</td><td>{fmt(v.median)}</td><td>{fmt(v.p90)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
      <p className="wf-note">* server stage durations from commit receipt (ms).</p>
      <div className="row">
        <button onClick={() => exp("json")} disabled={!turns.length}>Export JSON</button>
        <button onClick={() => exp("csv")} disabled={!turns.length}>Export CSV</button>
      </div>
    </aside>
  );
}
