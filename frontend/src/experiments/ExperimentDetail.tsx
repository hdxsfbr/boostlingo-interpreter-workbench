/** One experiment: provenance, the M5-summary columns, a latency chart, exports. */
import { useEffect, useState } from "react";
import { LatencyChart } from "./LatencyChart";
import { expApi, fmtDur, fmtNum, fmtUsd, summaryRows, type Experiment, type Turn } from "./api";

export function SummaryTable({ e }: { e: Pick<Experiment, "summary" | "id"> }) {
  const rows = summaryRows(e);
  if (!rows.length) return <p className="empty">No summary (no turns finished).</p>;
  return (
    <table className="results-table" data-testid={`summary-${e.id}`}>
      <thead>
        <tr>
          <th>Setup</th><th>n / done</th><th>H p50</th><th>H p90</th><th>H−gap p50</th><th>H−gap p90</th><th>tail p50</th>
          <th>chrF en→es</th><th>chrF es→en</th><th>chrF all</th><th>WER en</th><th>WER es</th><th>$/min</th><th>$ total</th><th>failures</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.setup} data-testid={`summary-row-${r.setup}`}>
            <td>{r.setup}</td><td>{r.n} / {r.done}</td><td>{fmtNum(r.H_p50)}</td><td>{fmtNum(r.H_p90)}</td><td>{fmtNum(r.Hgap_p50)}</td>
            <td>{fmtNum(r.Hgap_p90)}</td><td>{fmtNum(r.tail_p50)}</td><td>{fmtNum(r.chrF_en_es, 1)}</td><td>{fmtNum(r.chrF_es_en, 1)}</td>
            <td>{fmtNum(r.chrF_all, 1)}</td><td>{fmtNum(r.WER_en, 3)}</td><td>{fmtNum(r.WER_es, 3)}</td><td>{fmtUsd(r.usd_per_min)}</td>
            <td>{fmtUsd(r.usd_total, 4)}</td><td>{r.failures}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ExperimentDetail({ id }: { id: string }) {
  const [e, setE] = useState<Experiment | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setE(null);
    Promise.all([expApi.get(id), expApi.turns(id)]).then(([x, t]) => {
      setE(x);
      setTurns(t);
    }, (x) => setErr((x as Error).message));
  }, [id]);
  if (err) return <div className="save-error" role="alert">{err}</div>;
  if (!e) return <p className="empty">Loading…</p>;
  const took = e.started && e.finished ? e.finished - e.started : null;
  return (
    <div className="exp-detail" data-testid="exp-detail">
      <h2>
        {e.name} <span className={`badge status-${e.status}`}>{e.status}</span> {e.readonly ? <span className="badge">read-only</span> : null}
      </h2>
      <p className="meta">
        {e.id} · code {e.git_commit} · {new Date(e.created * 1000).toLocaleString()} · took {fmtDur(took)} · cost {fmtUsd(e.cost_usd, 4)}
        {e.estimate?.usd != null ? ` (estimated ${fmtUsd(e.estimate.usd, 4)})` : ""}
      </p>
      {e.error ? <div className="save-error">{e.error}</div> : null}
      <p className="meta">
        Models: {Object.entries(e.models).map(([s, m]) => `${s}: ${Object.values(m.models).join(", ")}`).join(" · ") || "–"}
      </p>
      <SummaryTable e={e} />
      <LatencyChart turns={turns} />
      <p className="row">
        <a href={expApi.exportUrl(e.id, "summary")} download data-testid="export-summary">Summary CSV</a>
        <a href={expApi.exportUrl(e.id, "turns")} download>Per-turn CSV</a>
        <a href={expApi.exportUrl(e.id, "json")} download>JSON</a>
      </p>
    </div>
  );
}
