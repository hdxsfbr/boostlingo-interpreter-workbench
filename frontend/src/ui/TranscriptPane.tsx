import { responseMs } from "../store/metrics";
import { joinSegments, type State, type TurnView } from "../store/reducer";
import { LatencyWaterfall } from "./LatencyWaterfall";

const Segs = ({ segs }: { segs: TurnView["source"] }) => (
  <>
    {joinSegments(segs).map((s, i) => (
      <span key={i} className={s.final ? "final" : "partial"}>{s.text} </span>
    ))}
  </>
);

export function TranscriptPane({ state }: { state: State }) {
  const items = [...state.timeline].reverse();
  return (
    <section className="card transcript" data-testid="transcript" aria-label="Transcript">
      <h2 className="card-title">Transcript</h2>
      {items.length === 0 && <p className="empty">Start a session, then hold a speaker button and talk.</p>}
      {items.map((it, i) => {
        if (it.kind === "switch") return <div key={`sw${i}`} className="switch">— switched {it.from} → {it.to} —</div>;
        const t = state.turns[it.id];
        return (
          <article key={t.id} className={`turn speaker-${t.speaker} status-${t.status}`} data-testid={`turn-${t.id}`}>
            <span className={`tag tag-${t.speaker}`} aria-label={`Speaker ${t.speaker}`}>{t.speaker}</span>
            <div className="turn-body">
              <div className="src"><label>{t.src.toUpperCase()}</label><Segs segs={t.source} /></div>
              <div className="tgt"><label>{t.tgt.toUpperCase()}</label><Segs segs={t.target} /></div>
              <div className="meta">
                #{t.id} · {t.mode} · <b>{t.status}</b>
                {t.reason && <em> ({t.reason})</em>}
                {t.latencyMs !== undefined && <> · <span className="mono">{Math.round(responseMs(t)!)} ms{responseMs(t) !== t.latencyMs ? "*" : ""}</span></>}
              </div>
              {t.browserMarks.commit_sent !== undefined && (
                <details className="timings">
                  <summary>Timings</summary>
                  <LatencyWaterfall turn={t} />
                </details>
              )}
            </div>
          </article>
        );
      })}
    </section>
  );
}
