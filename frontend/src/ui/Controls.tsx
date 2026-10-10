import type { Mode, Pipeline, Speaker } from "../session/protocol";
import type { TurnMode } from "../session/transports/realtimeWebrtc";

export type SwapOption = { name: string; ready: boolean; reason: string; model: string };
export type Swaps = { mt: SwapOption[]; tts: SwapOption[] };
export type RecordingConfig = { enabled: boolean; retention_days: number; max_upload_mb: number };

type Props = {
  swaps: Swaps | null;
  chosen: Record<string, string>;
  onProvider(kind: "mt" | "tts", name: string): void;
  /** A11: per-session "Record session" toggle (disabled unless the server enables it). */
  recording?: { config: RecordingConfig | null; on: boolean; onToggle(on: boolean): void };
  mode: Mode;
  turnMode: TurnMode;
  onTurnMode(m: TurnMode): void;
  /** Cascade VAD: STT/MT direction must be known, so the user picks who speaks. */
  vadSpeaker?: "A" | "B";
  onVadSpeaker?(s: "A" | "B"): void;
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
  pairs?: PairInfo[];
  canStart?: boolean;
  onPair?(id: string): void;
};

import type { PairInfo } from "../languages";

const NAMES = new Proxy({} as Record<string, string>, { get: (_t, k: string) => k.toUpperCase() });

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
      <span className={`av av-${sp}`} aria-hidden="true">{sp}</span>
      <span className="ptt-text">
        <span className="who">
          <strong>Speaker {sp}</strong>
          {p.active === sp && <span className="live"> ● SPEAKING</span>}
        </span>
        <span className="dir">{label}</span>
      </span>
      <kbd>hold {key}</kbd>
    </button>
  );
  return (
    <section className="controls">
      <div className="card ctl-card">
      <div className="row ctl">
        <div className="field">
        <span className="field-label" id="lbl-mode">Mode</span>
        <div className="seg" role="group" aria-labelledby="lbl-mode">
          {(["cascade", "realtime"] as Mode[]).map((m) => (
            <button key={m} className={p.mode === m ? "on" : ""} onClick={() => p.onMode(m)} data-testid={`mode-${m}`}>
              {m === "cascade" ? "Cascade" : "Realtime"}
            </button>
          ))}
        </div>
        </div>
        {p.mode === "realtime" && (
          <div className="field">
          <span className="field-label" id="lbl-turn">Turn taking</span>
          <div className="seg" role="group" aria-labelledby="lbl-turn">
            {(["ptt", "vad"] as TurnMode[]).map((m) => (
              <button key={m} className={p.turnMode === m ? "on" : ""} onClick={() => p.onTurnMode(m)} data-testid={`turn-${m}`}>
                {m === "ptt" ? "Push-to-talk" : "Auto (VAD)"}
              </button>
            ))}
          </div>
          </div>
        )}
        {p.mode === "cascade" && (
          <label className="field">
            <span className="field-label">Pipeline</span>
            <select value={p.pipeline} onChange={(e) => p.onPipeline(e.target.value as Pipeline)} data-testid="pipeline">
              <option value="cascade">STT → MT → TTS</option>
              <option value="loopback">Loopback (latency floor)</option>
            </select>
          </label>
        )}
        {p.mode === "cascade" && p.pipeline === "cascade" && p.swaps && (
          <>
            {(["mt", "tts"] as const).map((kind) => (
              <label key={kind} className="field" title="Provider swap by config (FR-9)">
                <span className="field-label">{kind === "mt" ? "Translator" : "Voice"}</span>
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
        <label className="field pair">
          <span className="field-label">Language pair</span>
          <select
            value={p.pairs?.find((x) => x.a === p.pair.a && x.b === p.pair.b)?.id ?? ""}
            disabled={p.running || !p.pairs?.length}
            onChange={(e) => p.onPair?.(e.target.value)}
            title={p.running ? "Stop the session to change the pair" : "Language pairs come from config/languages.yaml"}
            data-testid="pair-select"
          >
            {(p.pairs ?? []).map((x) => (
              <option key={x.id} value={x.id}>
                {x.label}{x.benchmarked ? "" : " (not benchmarked)"}
              </option>
            ))}
          </select>
        </label>
        {Object.keys(p.providers).length > 0 && (
          <span className="providers">{Object.entries(p.providers).map(([k, v]) => `${k}: ${v}`).join(" · ")}</span>
        )}
        <span className="spacer" />
        {p.running ? (
          <button className="danger" onClick={p.onStop} data-testid="stop">Stop session</button>
        ) : (
          <button className="primary" onClick={p.onStart} disabled={p.canStart === false} data-testid="start">Start session</button>
        )}
      </div>
      {p.recording && <RecordToggle {...p.recording} running={p.running} />}
      </div>
      {p.turnMode === "vad" ? (
        <div className="row ptts">
          <p className="vad-hint" data-testid="vad-listening">
            {!p.ready
              ? "Start the session to listen."
              : p.mode === "realtime"
                ? "Listening: speak in either language; the model detects the end of your turn (server VAD) and translates."
                : "Listening: the browser VAD ends your turn after a short silence. Pick who is speaking:"}
          </p>
          {p.mode === "cascade" && p.onVadSpeaker
            ? (["A", "B"] as const).map((sp) => (
                <button key={sp} className={p.vadSpeaker === sp ? "on" : ""} onClick={() => p.onVadSpeaker?.(sp)} data-testid={`vad-speaker-${sp}`}>
                  {sp === "A" ? `${NAMES[p.pair.a]} → ${NAMES[p.pair.b]}` : `${NAMES[p.pair.b]} → ${NAMES[p.pair.a]}`}
                </button>
              ))
            : null}
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

export function RecordToggle(p: { config: RecordingConfig | null; on: boolean; onToggle(on: boolean): void; running: boolean }) {
  const allowed = !!p.config?.enabled;
  const days = p.config?.retention_days ?? 30;
  return (
    <div className={`row record ${p.on ? "on" : ""}`}>
      <label title={allowed ? "Save both sides of every turn for audit" : "Recording is disabled in the server config (recording.enabled=false)"}>
        <input
          type="checkbox"
          checked={p.on}
          disabled={!allowed || p.running}
          onChange={(e) => p.onToggle(e.target.checked)}
          data-testid="record-toggle"
        />{" "}
        Record session
      </label>
      {!allowed ? (
        <span className="record-note" data-testid="record-disabled">Disabled by server config.</span>
      ) : p.on ? (
        <span className="record-note consent" data-testid="record-consent">
          Both speakers&apos; audio (original and translation) is saved on this server for {days} days for audit. Tell everyone on
          the call and get their consent before starting.
        </span>
      ) : (
        <span className="record-note">Off: nothing is recorded. Set it before starting the session.</span>
      )}
    </div>
  );
}
