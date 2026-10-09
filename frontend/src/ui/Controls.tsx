import type { Mode, Pipeline, Speaker } from "../session/protocol";
import type { TurnMode } from "../session/transports/realtimeWebrtc";

export type SwapOption = { name: string; ready: boolean; reason: string; model: string };
export type Swaps = { mt: SwapOption[]; tts: SwapOption[] };

type Props = {
  swaps: Swaps | null;
  chosen: Record<string, string>;
  onProvider(kind: "mt" | "tts", name: string): void;
  mode: Mode;
  turnMode: TurnMode;
  onTurnMode(m: TurnMode): void;
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
        {p.mode === "realtime" && (
          <div className="toggle" role="group" aria-label="Turn taking">
            {(["ptt", "vad"] as TurnMode[]).map((m) => (
              <button key={m} className={p.turnMode === m ? "on" : ""} onClick={() => p.onTurnMode(m)} data-testid={`turn-${m}`}>
                {m === "ptt" ? "Push-to-talk" : "Auto (VAD)"}
              </button>
            ))}
          </div>
        )}
        {p.mode === "cascade" && (
          <label>
            Pipeline{" "}
            <select value={p.pipeline} onChange={(e) => p.onPipeline(e.target.value as Pipeline)} data-testid="pipeline">
              <option value="cascade">STT → MT → TTS</option>
              <option value="loopback">Loopback (latency floor)</option>
            </select>
          </label>
        )}
        {p.mode === "cascade" && p.pipeline === "cascade" && p.swaps && (
          <>
            {(["mt", "tts"] as const).map((kind) => (
              <label key={kind} title="Provider swap by config (FR-9)">
                {kind === "mt" ? "Translator" : "Voice"}{" "}
                <select value={p.chosen[kind] ?? p.swaps![kind][0]?.name} onChange={(e) => p.onProvider(kind, e.target.value)} data-testid={`swap-${kind}`}>
                  {p.swaps![kind].map((o) => (
                    <option key={o.name} value={o.name} disabled={!o.ready} title={o.reason}>
                      {o.name} ({o.model}){o.ready ? "" : ` (unavailable: ${o.reason})`}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </>
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
      {p.mode === "realtime" && p.turnMode === "vad" ? (
        <div className="row ptts">
          <p className="vad-hint" data-testid="vad-listening">
            {p.ready ? "Listening: speak in either language; the model detects the end of your turn (server VAD) and translates." : "Start the session to listen."}
          </p>
        </div>
      ) : (
        <div className="row ptts">
          {ptt("A", `${NAMES[p.pair.a]} → ${NAMES[p.pair.b]}`, "F")}
          {ptt("B", `${NAMES[p.pair.b]} → ${NAMES[p.pair.a]}`, "J")}
        </div>
      )}
      <p className="hint">Use headphones. The mic is muted while a translation plays; pressing a speaker button interrupts playback.</p>
    </section>
  );
}
