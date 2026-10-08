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
    <section className="transcript" data-testid="transcript">
      {items.length === 0 && <p className="empty">Start a session, then hold a speaker button and talk.</p>}
      {items.map((it, i) => {
        if (it.kind === "switch") return <div key={`sw${i}`} className="switch">— switched {it.from} → {it.to} —</div>;
        const t = state.turns[it.id];
        return (
          <article key={t.id} className={`turn speaker-${t.speaker} status-${t.status}`} data-testid={`turn-${t.id}`}>
            <div className="meta">
              #{t.id} · {t.mode} · Speaker {t.speaker} · {t.src.toUpperCase()}→{t.tgt.toUpperCase()} · <b>{t.status}</b>
              {t.reason && <em> ({t.reason})</em>}
            </div>
            <div className="src"><label>{t.src.toUpperCase()}</label><Segs segs={t.source} /></div>
            <div className="tgt"><label>{t.tgt.toUpperCase()}</label><Segs segs={t.target} /></div>
            <LatencyWaterfall turn={t} />
          </article>
        );
      })}
    </section>
  );
}
