/** Experiments tab (DESIGN A13): create -> estimate -> (confirm) -> run with live
 * progress -> history, detail, compare. The backend runs the existing harness. */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ExperimentDetail } from "./ExperimentDetail";
import {
  ApiError, compare, expApi, fmtDur, fmtNum, fmtUsd,
  type Estimate, type Experiment, type ExperimentConfig, type ExperimentListItem, type Progress, type SetupsResponse,
} from "./api";

const DEFAULT: ExperimentConfig = { name: "", setups: [], utterances: "short", ids: [], directions: "both", passes: 1, allow_elevenlabs: false };

function NewExperiment({ meta, busy, onStarted }: { meta: SetupsResponse; busy: boolean; onStarted(e: Experiment): void }) {
  const [cfg, setCfg] = useState<ExperimentConfig>({ ...DEFAULT, setups: meta.default_setups, name: `Experiment ${new Date().toLocaleString()}` });
  const [est, setEst] = useState<Estimate | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [sending, setSending] = useState(false);
  const set = (p: Partial<ExperimentConfig>) => {
    setConfirming(false);
    setCfg((c) => ({ ...c, ...p }));
  };

  useEffect(() => {
    const t = setTimeout(() => {
      expApi.estimate(cfg).then((e) => { setEst(e); setErr(null); }, (e) => { setEst(null); setErr((e as Error).message); });
    }, 250);
    return () => clearTimeout(t);
  }, [cfg]);

  const run = async (confirm: boolean) => {
    if (!est) return;
    if (est.needs_confirmation && !confirm) {
      setConfirming(true);
      return;
    }
    setSending(true);
    try {
      onStarted(await expApi.run(cfg, confirm));
      setConfirming(false);
    } catch (e) {
      const a = e as ApiError;
      if (a.status === 428) setConfirming(true);
      setErr(a.message);
    } finally {
      setSending(false);
    }
  };

  const toggleSetup = (name: string, on: boolean) => set({ setups: on ? [...cfg.setups, name] : cfg.setups.filter((s) => s !== name) });
  const toggleId = (id: string, on: boolean) => set({ ids: on ? [...cfg.ids, id] : cfg.ids.filter((x) => x !== id) });
  const selected = meta.setups.filter((s) => cfg.setups.includes(s.name));
  return (
    <section className="card exp-new" data-testid="exp-new">
      <h2>New experiment</h2>
      <label className="field">Name <input value={cfg.name} maxLength={80} onChange={(e) => set({ name: e.target.value })} data-testid="exp-name" /></label>
      <fieldset>
        <legend>Setups</legend>
        {meta.setups.map((s) => (
          <label key={s.name} className={`setup ${s.unavailable ? "off" : ""}`} title={s.unavailable || s.label}>
            <input type="checkbox" checked={cfg.setups.includes(s.name)} disabled={!!s.unavailable} onChange={(e) => toggleSetup(s.name, e.target.checked)} data-testid={`exp-setup-${s.name}`} />{" "}
            {s.label}
            {s.unavailable ? <small> (unavailable: {s.unavailable})</small> : null}
          </label>
        ))}
        {selected.filter((s) => s.warning).map((s) => (
          <p key={s.name} className="warn" data-testid={`exp-warning-${s.name}`}>⚠ {s.warning}</p>
        ))}
        {cfg.setups.includes("cascade-elevenlabs") ? (
          <label className="warn">
            <input type="checkbox" checked={cfg.allow_elevenlabs} onChange={(e) => set({ allow_elevenlabs: e.target.checked })} data-testid="exp-allow-elevenlabs" /> I accept spending
            ElevenLabs credits (the credit guard still refuses runs over the session/month caps)
          </label>
        ) : null}
      </fieldset>
      <fieldset>
        <legend>Utterances</legend>
        {(["full", "short", "custom"] as const).map((u) => (
          <label key={u}>
            <input type="radio" name="utt" checked={cfg.utterances === u} onChange={() => set({ utterances: u, ids: u === "custom" ? cfg.ids : [] })} data-testid={`exp-utt-${u}`} />{" "}
            {u === "full" ? "Full set (48)" : u === "short" ? "Short only (16)" : "Custom subset"}
          </label>
        ))}
        {cfg.utterances === "custom" ? (
          <div className="id-grid" data-testid="exp-ids">
            {meta.utterances.map((u) => (
              <label key={u.id} title={u.text}>
                <input type="checkbox" checked={cfg.ids.includes(u.id)} onChange={(e) => toggleId(u.id, e.target.checked)} data-testid={`exp-id-${u.id}`} /> {u.id}
              </label>
            ))}
          </div>
        ) : null}
      </fieldset>
      <div className="row">
        <label>
          Directions{" "}
          <select value={cfg.directions} onChange={(e) => set({ directions: e.target.value })} data-testid="exp-directions">
            {meta.directions.map((d) => (
              <option key={d.value} value={d.value}>{d.label}</option>
            ))}
          </select>
        </label>
        <label>
          Passes <input type="number" min={1} max={5} value={cfg.passes} onChange={(e) => set({ passes: Number(e.target.value) || 1 })} data-testid="exp-passes" />
        </label>
      </div>
      <div className="estimate" data-testid="exp-estimate">
        {est ? (
          <>
            <table className="results-table">
              <thead><tr><th>Setup</th><th>Turns</th><th>Voiced min</th><th>M5 $/min</th><th>Est. cost</th><th>Est. time</th></tr></thead>
              <tbody>
                {est.per_setup.map((r) => (
                  <tr key={r.setup}>
                    <td>{r.setup}</td><td>{r.utterances}</td><td>{r.source_min.toFixed(2)}</td><td>{fmtUsd(r.usd_per_min)}</td><td>{fmtUsd(r.usd, 4)}</td><td>{fmtDur(r.duration_s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p>
              <b data-testid="exp-estimate-total">Estimated {fmtUsd(est.usd, 4)}</b> · about {fmtDur(est.duration_s)} · {est.turns} turns.{" "}
              <span className="hint">{est.basis}; prices as of {est.pricing_as_of}.</span>
            </p>
            {est.per_setup.some((r) => r.utterances < 12) ? (
              <p className="warn" data-testid="exp-small-sample">
                Small sample: fewer than 12 turns per setup. 6-turn latency medians have swung by ~500 ms between identical runs (a slow spell at a
                provider), so add utterances or passes before reading latency differences.
              </p>
            ) : null}
          </>
        ) : null}
        {err ? <div className="save-error" role="alert" data-testid="exp-error">{err}</div> : null}
      </div>
      {confirming && est ? (
        <div className="confirm" role="alertdialog" data-testid="exp-confirm">
          The estimate ({fmtUsd(est.usd, 2)}) is above the {fmtUsd(est.confirm_above_usd, 2)} confirmation threshold.{" "}
          <button className="primary" onClick={() => void run(true)} disabled={sending} data-testid="exp-confirm-run">Run anyway</button>{" "}
          <button onClick={() => setConfirming(false)}>Cancel</button>
        </div>
      ) : null}
      <button className="primary" disabled={!est || busy || sending} onClick={() => void run(false)} data-testid="exp-run" title={busy ? "Another experiment is running" : ""}>
        {busy ? "Another experiment is running" : "Run experiment"}
      </button>
    </section>
  );
}

function LiveProgress({ id, onFinished }: { id: string; onFinished(): void }) {
  const [p, setP] = useState<Partial<Progress> & { status?: string; last?: { id: string; status: string; H_ms: number | null } }>({});
  const [cancelling, setCancelling] = useState(false);
  useEffect(() => {
    const es = new EventSource(expApi.eventsUrl(id));
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      setP((old) => ({ ...old, ...ev, ...(ev.progress ?? {}) }));
      if (ev.type === "status" && !["running", "queued"].includes(ev.status)) {
        es.close();
        onFinished();
      }
      if (ev.type === "snapshot" && !["running", "queued"].includes(ev.status)) {
        es.close();
        onFinished();
      }
    };
    return () => es.close();
  }, [id, onFinished]);
  const pct = p.total ? (100 * (p.done ?? 0)) / p.total : 0;
  return (
    <section className="card exp-live" data-testid="exp-live">
      <h2>Running: {id}</h2>
      <div className="bar"><div style={{ width: `${pct}%` }} /></div>
      <p data-testid="exp-live-status">
        Setup {p.setup_index ?? 0}/{p.setups ?? "?"} <b>{p.setup ?? "starting"}</b> · now: {p.utterance ?? "–"} · {p.done ?? 0}/{p.total ?? "?"} turns ·
        running p50 H {fmtNum(p.p50_H_ms)} ms · failures {p.failures ?? 0} · cost so far {fmtUsd(p.cost_usd, 4)} · {fmtDur(p.elapsed_s)}
      </p>
      {p.last ? <p className="hint">last: {p.last.id} {p.last.status} {fmtNum(p.last.H_ms)} ms</p> : null}
      <button
        onClick={async () => {
          setCancelling(true);
          try {
            await expApi.cancel(id);
          } finally {
            setCancelling(false);
          }
        }}
        disabled={cancelling}
        data-testid="exp-cancel"
      >
        {cancelling ? "Stopping…" : "Cancel"}
      </button>
    </section>
  );
}

function Compare({ a, b }: { a: string; b: string }) {
  const [ea, setA] = useState<Experiment | null>(null);
  const [eb, setB] = useState<Experiment | null>(null);
  useEffect(() => {
    void expApi.get(a).then(setA);
    void expApi.get(b).then(setB);
  }, [a, b]);
  const rows = useMemo(() => (ea && eb ? compare(ea, eb) : []), [ea, eb]);
  if (!ea || !eb) return <p className="empty">Loading…</p>;
  const setups = [...new Set(rows.map((r) => r.setup))];
  return (
    <section data-testid="exp-compare">
      <h2>Compare: {ea.name} (A) vs {eb.name} (B)</h2>
      <table className="results-table">
        <thead><tr><th>Setup</th><th>Metric</th><th>A</th><th>B</th><th>B − A</th></tr></thead>
        <tbody>
          {setups.flatMap((s) =>
            rows.filter((r) => r.setup === s).map((r) => (
              <tr key={`${s}-${r.key}`}>
                <td>{r.key === "H_p50" ? s : ""}</td><td>{r.key}</td><td>{fmtNum(r.a, r.key.startsWith("WER") || r.key === "usd_per_min" ? 3 : r.key === "chrF_all" ? 1 : 0)}</td>
                <td>{fmtNum(r.b, r.key.startsWith("WER") || r.key === "usd_per_min" ? 3 : r.key === "chrF_all" ? 1 : 0)}</td>
                <td className={r.delta == null ? "" : r.delta > 0 ? "up" : r.delta < 0 ? "down" : ""}>{r.delta == null ? "–" : (r.delta > 0 ? "+" : "") + r.delta}</td>
              </tr>
            )),
          )}
        </tbody>
      </table>
      <p className="hint">Lower is better for latency, WER, $/min and failures; higher is better for chrF.</p>
    </section>
  );
}

export function ExperimentsTab() {
  const [meta, setMeta] = useState<SetupsResponse | null>(null);
  const [list, setList] = useState<ExperimentListItem[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [view, setView] = useState<{ kind: "detail"; id: string } | { kind: "compare"; a: string; b: string } | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [l, r] = await Promise.all([expApi.list(), expApi.running()]);
      setList(l);
      setRunning(r.id);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);
  useEffect(() => {
    expApi.setups().then(setMeta, (e) => setErr((e as Error).message));
    void refresh();
  }, [refresh]);
  const finished = useCallback(() => void refresh(), [refresh]);

  return (
    <div className="experiments" data-testid="experiments-tab">
      {err ? <div className="save-error" role="alert">{err}</div> : null}
      <div className="exp-grid">
        <div>
          {meta ? <NewExperiment meta={meta} busy={!!running} onStarted={(e) => { setRunning(e.id); void refresh(); }} /> : <p className="empty">Loading setups…</p>}
          {running ? <LiveProgress id={running} onFinished={finished} /> : null}
        </div>
        <section className="card exp-history">
          <h2>History</h2>
          <table className="results-table" data-testid="exp-history">
            <thead><tr><th /><th>Name</th><th>Status</th><th>Setups</th><th>Cost (est.)</th><th>When</th></tr></thead>
            <tbody>
              {list.map((e) => (
                <tr key={e.id} data-testid={`exp-row-${e.id}`}>
                  <td>
                    <input type="checkbox" aria-label="pick for compare" checked={picked.includes(e.id)} onChange={(x) => setPicked((p) => (x.target.checked ? [...p, e.id].slice(-2) : p.filter((i) => i !== e.id)))} />
                  </td>
                  <td><button className="link" onClick={() => setView({ kind: "detail", id: e.id })} data-testid={`exp-open-${e.id}`}>{e.name}</button>{e.readonly ? " (read-only)" : ""}</td>
                  <td><span className={`badge status-${e.status}`}>{e.status}</span>{e.progress && e.status === "running" ? ` ${e.progress.done}/${e.progress.total}` : ""}</td>
                  <td>{e.setups.join(", ")}</td>
                  <td>{fmtUsd(e.cost_usd, 4)}{e.estimate_usd != null ? ` (${fmtUsd(e.estimate_usd, 4)})` : ""}</td>
                  <td>{new Date(e.created * 1000).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <button disabled={picked.length !== 2} onClick={() => setView({ kind: "compare", a: picked[0], b: picked[1] })} data-testid="exp-compare-btn">
            Compare the two ticked
          </button>
        </section>
      </div>
      {view?.kind === "detail" ? <ExperimentDetail id={view.id} /> : null}
      {view?.kind === "compare" ? <Compare a={view.a} b={view.b} /> : null}
    </div>
  );
}
