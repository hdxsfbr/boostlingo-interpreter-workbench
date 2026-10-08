import type { Mode, Pipeline, Speaker } from "../session/protocol";

type Props = {
  mode: Mode;
  pipeline: Pipeline;
  pair: { a: string; b: string };
  running: boolean;
  ready: boolean;
  active: Speaker | null;
  providers: Record<string, string>;
  onStart(): void;
  onStop(): void;
  onMode(m: Mode): void;
  onPipeline(p: Pipeline): void;
  onDown(s: Speaker): void;
  onUp(s: Speaker): void;
};

const NAMES: Record<string, string> = { en: "EN", es: "ES" };

export function Controls(p: Props) {
  const ptt = (sp: Speaker, label: string, key: string) => (
    <button
      className={`ptt ${p.active === sp ? "held" : ""}`}
      disabled={!p.ready}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        p.onDown(sp);
      }}
      onPointerUp={() => p.onUp(sp)}
      onPointerCancel={() => p.onUp(sp)}
      data-testid={`ptt-${sp}`}
    >
      <strong>Speaker {sp}</strong>
      <span>{label}</span>
      <kbd>hold {key}</kbd>
    </button>
  );
  return (
    <section className="controls">
      <div className="row">
        <div className="toggle" role="group" aria-label="Mode">
          {(["cascade", "realtime"] as Mode[]).map((m) => (
            <button key={m} className={p.mode === m ? "on" : ""} onClick={() => p.onMode(m)} data-testid={`mode-${m}`}>
              {m === "cascade" ? "Cascade" : "Realtime"}
            </button>
          ))}
        </div>
        {p.mode === "cascade" && (
          <label>
            Pipeline{" "}
            <select value={p.pipeline} onChange={(e) => p.onPipeline(e.target.value as Pipeline)} data-testid="pipeline">
              <option value="cascade">STT → MT → TTS</option>
              <option value="loopback">Loopback (latency floor)</option>
            </select>
          </label>
        )}
        <span className="pair">
          Pair: {NAMES[p.pair.a]} ↔ {NAMES[p.pair.b]}
        </span>
        {Object.keys(p.providers).length > 0 && (
          <span className="providers">{Object.entries(p.providers).map(([k, v]) => `${k}: ${v}`).join(" · ")}</span>
        )}
        <span className="spacer" />
        {p.running ? (
          <button onClick={p.onStop} data-testid="stop">Stop</button>
        ) : (
          <button className="primary" onClick={p.onStart} data-testid="start">Start session</button>
        )}
      </div>
      <div className="row ptts">
        {ptt("A", `${NAMES[p.pair.a]} → ${NAMES[p.pair.b]}`, "F")}
        {ptt("B", `${NAMES[p.pair.b]} → ${NAMES[p.pair.a]}`, "J")}
      </div>
      <p className="hint">Use headphones. The mic is muted while a translation plays; pressing a speaker button interrupts playback.</p>
    </section>
  );
}
