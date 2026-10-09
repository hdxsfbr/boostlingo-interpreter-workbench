/** One clip at a time (UX from Butler's rate.py): direction, source, reference,
 * audio, 1-5 for adequacy/fluency/naturalness, notes, Back / Save & next. */
import { useCallback, useEffect, useRef, useState } from "react";
import { DIMS, reviewApi, type Dim, type SetDetail } from "./api";
import { applyKey, EMPTY, isComplete, resumeIndex, type Draft } from "./rateLogic";

const LABELS: Record<Dim, [string, string]> = {
  adequacy: ["Accuracy", "Did the meaning come through correctly?"],
  fluency: ["Fluency", "Natural, grammatical language?"],
  naturalness: ["Voice", "Does the voice sound human and pleasant?"],
};

type Props = { set: SetDetail; rater: string; onChanged(d: SetDetail): void; onDone(): void };

export function RateView({ set, rater, onChanged, onDone }: Props) {
  const items = set.items;
  const [i, setI] = useState(() => resumeIndex(items, set.ratings));
  const [draft, setDraft] = useState<Draft>(() => ({ cur: { ...EMPTY, ...set.ratings[items[i]?.item_id] }, focus: 0 }));
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);
  const item = items[i];

  // Load the draft for the current item and autoplay it.
  useEffect(() => {
    if (!item) return;
    // a focused button would also react to Space/Enter; the shortcuts own those keys here
    (document.activeElement as HTMLElement | null)?.blur?.();
    setDraft({ cur: { ...EMPTY, ...set.ratings[item.item_id] }, focus: 0 });
    void audio.current?.play().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [i, item?.item_id]);

  const save = useCallback(async (): Promise<boolean> => {
    if (!item) return false;
    setBusy(true);
    try {
      const r = await reviewApi.save(set.id, item.item_id, rater, draft.cur);
      onChanged({ ...set, progress: r.progress, ratings: { ...set.ratings, [item.item_id]: r.saved } });
      setMsg({ kind: "ok", text: isComplete(r.saved) ? "Saved" : "Saved (some scores empty)" });
      setTimeout(() => setMsg((m) => (m?.kind === "ok" ? null : m)), 1200);
      return true;
    } catch (e) {
      setMsg({ kind: "err", text: `Save failed: ${(e as Error).message}. Your scores are still on screen; try again.` });
      return false;
    } finally {
      setBusy(false);
    }
  }, [item, set, rater, draft.cur, onChanged]);

  const next = useCallback(async () => {
    if (busy || !(await save())) return;
    if (i < items.length - 1) setI(i + 1);
    else onDone();
  }, [busy, save, i, items.length, onDone]);

  const back = useCallback(async () => {
    if (busy || !(await save())) return;
    if (i > 0) setI(i - 1);
  }, [busy, save, i]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.tagName === "SELECT")) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const r = applyKey(draft, e.key, e.shiftKey);
      if (!r.handled) return;
      e.preventDefault();
      setDraft(r.draft);
      if (r.action === "toggle-play" && audio.current) {
        if (audio.current.paused) void audio.current.play().catch(() => {});
        else audio.current.pause();
      }
      if (r.action === "save-next") void next();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [draft, next]);

  if (!item) return <p className="empty">This set has no items.</p>;
  const pct = (100 * set.progress.done) / Math.max(1, set.progress.total);
  return (
    <div className="rate" data-testid="rate-view">
      <div className="rate-head">
        <strong data-testid="rate-pos">
          {i + 1} of {items.length}
        </strong>
        <span className="rate-done" data-testid="rate-progress">
          {set.progress.done}/{set.progress.total} rated{set.progress.complete ? " · complete" : ""}
        </span>
      </div>
      <div className="bar" role="progressbar" aria-valuenow={set.progress.done} aria-valuemax={set.progress.total}>
        <div style={{ width: `${pct}%` }} />
      </div>
      <div className="card">
        <div className="lbl">Direction</div>
        <div className="txt" data-testid="rate-direction">
          {item.direction}
          {item.variant ? <span className="variant"> · {item.variant}</span> : null}
        </div>
        <div className="lbl">What the speaker said</div>
        <div className="txt" data-testid="rate-source">{item.source_text || "–"}</div>
        {item.reference ? (
          <>
            <div className="lbl">Reference translation</div>
            <div className="txt">{item.reference}</div>
          </>
        ) : null}
        {item.target_text ? (
          <>
            <div className="lbl">Interpreter output (transcript)</div>
            <div className="txt">{item.target_text}</div>
          </>
        ) : null}
        <audio ref={audio} src={item.audio_url} controls preload="auto" data-testid="rate-audio" />
        {DIMS.map((d, k) => (
          <div className={`score-row ${draft.focus === k ? "focus" : ""}`} key={d} data-testid={`row-${d}`}>
            <b onClick={() => setDraft({ ...draft, focus: k })}>
              {LABELS[d][0]}
              {draft.focus === k ? " ◀" : ""}
            </b>
            <span className="opts">
              {[1, 2, 3, 4, 5].map((v) => (
                <button
                  key={v}
                  className={draft.cur[d] === v ? "on" : ""}
                  onClick={() => setDraft({ cur: { ...draft.cur, [d]: v }, focus: Math.min(2, k + 1) })}
                  data-testid={`score-${d}-${v}`}
                  tabIndex={-1}
                >
                  {v}
                </button>
              ))}
            </span>
            <small>{LABELS[d][1]}</small>
          </div>
        ))}
        <div className="lbl">Notes (optional)</div>
        <textarea value={draft.cur.notes} onChange={(e) => setDraft({ ...draft, cur: { ...draft.cur, notes: e.target.value } })} data-testid="rate-notes" maxLength={2000} />
        {msg ? (
          <div className={msg.kind === "err" ? "save-error" : "save-ok"} role={msg.kind === "err" ? "alert" : "status"} data-testid={msg.kind === "err" ? "save-error" : "save-ok"}>
            {msg.text}
          </div>
        ) : null}
        <div className="nav">
          <button onClick={() => void back()} disabled={busy || i === 0} data-testid="rate-back">
            ← Back
          </button>
          <button className="primary" onClick={() => void next()} disabled={busy} data-testid="rate-next">
            {i < items.length - 1 ? "Save & next →" : "Save & finish"}
          </button>
        </div>
      </div>
      <p className="hint">Keys: 1-5 scores the selected row and moves down, Tab cycles rows, Space plays/pauses, Enter saves and moves on. Typing in Notes doesn&apos;t trigger shortcuts.</p>
    </div>
  );
}
