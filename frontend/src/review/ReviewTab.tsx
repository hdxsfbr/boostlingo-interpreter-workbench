/** Review tab (DESIGN A12): pick a rater name, open a blind benchmark set or a
 * recorded session, rate clip by clip, then see Results. */
import { useCallback, useEffect, useState } from "react";
import { reviewApi, type SessionInfo, type SetDetail, type SetSummary } from "./api";
import { RateView } from "./RateView";
import { ResultsView } from "./ResultsView";

const RATER_KEY = "wb.review.rater";

export function ReviewTab() {
  const [rater, setRater] = useState(() => localStorage.getItem(RATER_KEY) ?? "");
  const [nameDraft, setNameDraft] = useState(rater);
  const [sets, setSets] = useState<SetSummary[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [open, setOpen] = useState<SetDetail | null>(null);
  const [view, setView] = useState<"rate" | "results">("rate");
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!rater) return;
    try {
      setSets(await reviewApi.sets(rater));
      setSessions(await reviewApi.sessions());
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [rater]);
  useEffect(() => void refresh(), [refresh]);

  const openSet = async (id: string, v?: "rate" | "results") => {
    try {
      const d = await reviewApi.set(id, rater);
      setOpen(d);
      setView(v ?? (d.progress.complete ? "results" : "rate"));
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const reloadOpen = async () => open && setOpen(await reviewApi.set(open.id, rater));

  const applyName = () => {
    const n = nameDraft.trim().replace(/\s+/g, " ").toLowerCase();
    if (!n) return;
    localStorage.setItem(RATER_KEY, n);
    setRater(n);
    setOpen(null);
  };

  return (
    <div className="review" data-testid="review-tab">
      <div className="controls row">
        <label>
          Rater name{" "}
          <input value={nameDraft} onChange={(e) => setNameDraft(e.target.value)} onKeyDown={(e) => e.key === "Enter" && applyName()} placeholder="e.g. andre" data-testid="rater-name" maxLength={40} />
        </label>
        <button onClick={applyName} data-testid="rater-use">
          Use
        </button>
        {rater ? <span className="hint">Rating as <b>{rater}</b> (no login; ratings are saved under this name)</span> : null}
        {open ? (
          <>
            <span className="spacer" />
            <button onClick={() => { setOpen(null); void refresh(); }} data-testid="review-back-to-sets">
              ← All sets
            </button>
          </>
        ) : null}
      </div>
      {err ? <div className="save-error" role="alert">{err}</div> : null}
      {!rater ? (
        <p className="empty">Enter your name to start rating.</p>
      ) : !open ? (
        <div className="sets">
          <h2>Review sets</h2>
          <table className="results-table" data-testid="sets-table">
            <thead>
              <tr><th>Set</th><th>Kind</th><th>Your progress</th><th /></tr>
            </thead>
            <tbody>
              {sets.map((s) => (
                <tr key={s.id} data-testid={`set-${s.id}`}>
                  <td>{s.title}</td>
                  <td>{s.blind ? "blind benchmark" : "recorded session"}</td>
                  <td data-testid={`set-progress-${s.id}`}>
                    {s.progress ? `${s.progress.done}/${s.progress.total}${s.progress.complete ? " · complete" : ""}` : "–"}
                  </td>
                  <td>
                    <button onClick={() => void openSet(s.id, "rate")} data-testid={`open-${s.id}`}>{s.progress?.done ? "Resume" : "Start"}</button>{" "}
                    <button onClick={() => void openSet(s.id, "results")} data-testid={`results-${s.id}`}>Results</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2>Recorded sessions</h2>
          {sessions.length === 0 ? (
            <p className="empty">No recorded sessions yet. Recording is opt-in (README, "Session recording").</p>
          ) : (
            <table className="results-table" data-testid="sessions-table">
              <thead>
                <tr><th>Session</th><th>Turns with audio</th><th>Mode</th><th /></tr>
              </thead>
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.session_id}>
                    <td>{s.session_id}</td>
                    <td>{s.turns}</td>
                    <td>{s.modes.join(", ") || "?"}</td>
                    <td>
                      <button
                        onClick={async () => {
                          try {
                            const { set_id } = await reviewApi.importSession(s.session_id);
                            await openSet(set_id, "rate");
                          } catch (e) {
                            setErr((e as Error).message);
                          }
                        }}
                      >
                        {s.set_id ? "Open (refresh turns)" : "Create review set"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : (
        <div>
          <div className="row review-head">
            <h2>{open.title}</h2>
            <div className="toggle" role="group" aria-label="Review view">
              {(["rate", "results"] as const).map((v) => (
                <button key={v} className={view === v ? "on" : ""} onClick={() => { setView(v); void reloadOpen(); }} data-testid={`view-${v}`}>
                  {v === "rate" ? "Rate" : "Results"}
                </button>
              ))}
            </div>
            {open.blind ? <span className="hint">{open.revealed ? "Variants revealed" : "Blind: variant names hidden"}</span> : null}
          </div>
          {view === "rate" ? (
            <RateView key={open.id} set={open} rater={rater} onChanged={setOpen} onDone={() => void reloadOpen().then(() => setView("results"))} />
          ) : (
            <ResultsView set={open} rater={rater} onRevealed={() => void reloadOpen()} />
          )}
        </div>
      )}
    </div>
  );
}
