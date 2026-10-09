/** Per-variant mean (median, sd, range) per dimension, overall and by direction,
 * next to M5 latency and chrF. Locked for blind sets until Reveal / completion. */
import { useEffect, useState } from "react";
import { ApiError, DIMS, reviewApi, type Results, type SetDetail } from "./api";
import { fmtStat } from "./rateLogic";

type Props = { set: SetDetail; rater: string; onRevealed(): void };

export function ResultsView({ set, rater, onRevealed }: Props) {
  const [raters, setRaters] = useState<"me" | "all">("me");
  const [res, setRes] = useState<Results | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);

  useEffect(() => {
    setErr(null);
    reviewApi.results(set.id, rater, raters).then(setRes, (e) => {
      setRes(null);
      setErr(e as ApiError);
    });
  }, [set.id, rater, raters, set.revealed]);

  const reveal = async () => {
    try {
      await reviewApi.reveal(set.id, rater);
      onRevealed();
    } catch (e) {
      setErr(e as ApiError);
    }
  };

  if (err?.status === 403)
    return (
      <div className="card locked" data-testid="results-locked">
        <p>
          Results are hidden while you rate blind ({set.progress.done}/{set.progress.total} done). They appear when you finish every
          clip, or now if you reveal the variant names. Ratings you save after revealing are marked as such.
        </p>
        <button onClick={() => void reveal()} data-testid="reveal">
          Reveal variants
        </button>
      </div>
    );
  if (err) return <div className="save-error" role="alert">Could not load results: {err.message}</div>;
  if (!res) return <p className="empty">Loading…</p>;
  const scopes = [...new Set(res.rows.map((r) => r.scope))];
  return (
    <div className="results" data-testid="results-view">
      <div className="row">
        <div className="toggle" role="group" aria-label="Raters">
          {(["me", "all"] as const).map((m) => (
            <button key={m} className={raters === m ? "on" : ""} onClick={() => setRaters(m)} data-testid={`raters-${m}`}>
              {m === "me" ? `My ratings (${rater})` : "All raters"}
            </button>
          ))}
        </div>
        {raters === "all" ? <span className="hint">{res.rater_count} rater(s) pooled</span> : null}
        <span className="spacer" />
        <a href={reviewApi.resultsCsvUrl(set.id, rater, raters)} download data-testid="export-results">
          Export results CSV
        </a>
        <a href={reviewApi.ratingsCsvUrl(set.id, rater)} download>
          Export my ratings CSV
        </a>
      </div>
      {scopes.map((scope) => (
        <section key={scope}>
          <h3>{scope === "all" ? "Overall" : scope}</h3>
          <table className="results-table" data-testid={`results-${scope}`}>
            <thead>
              <tr>
                <th>Variant</th>
                <th>n</th>
                {DIMS.map((d) => (
                  <th key={d}>{d} mean / median (sd, range)</th>
                ))}
                <th>Composite</th>
                <th>M5 H p50 / p90 (ms)</th>
                <th>M5 chrF</th>
              </tr>
            </thead>
            <tbody>
              {res.rows
                .filter((r) => r.scope === scope)
                .map((r) => (
                  <tr key={r.variant} data-testid={`result-${r.variant}-${scope}`}>
                    <td>{r.variant}</td>
                    <td>{r.n}</td>
                    {DIMS.map((d) => (
                      <td key={d}>{fmtStat(r[d])}</td>
                    ))}
                    <td className="composite">{r.composite_mean?.toFixed(2) ?? "–"}</td>
                    <td>{r.m5 ? `${r.m5.H_p50 ?? "–"} / ${r.m5.H_p90 ?? "–"}` : "–"}</td>
                    <td>{r.m5?.chrF ?? "–"}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </section>
      ))}
      <p className="hint">M5 numbers are the full benchmark run per variant (all 48 utterances; H is the overall headline latency, chrF per direction). Ratings: 1-5.</p>
    </div>
  );
}
