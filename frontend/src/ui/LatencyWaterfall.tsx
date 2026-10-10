import { LIMIT_MS, TARGET_MS } from "../store/metrics";
import type { TurnView } from "../store/reducer";

/** Per-turn waterfall (FR-7). Browser marks are exact (one clock). Server
 * stage marks are durations from the server receiving the commit; they are
 * placed after the browser's commit_sent mark and labelled as estimates. */
const SERVER_ORDER = ["stt_final", "mt_first_token", "mt_first_chunk", "tts_request", "tts_first_byte", "audio_first_sent", "tail_tts_first_byte"];
const LABEL: Record<string, string> = {
  commit_sent: "commit sent",
  stt_final: "STT final",
  mt_first_token: "MT 1st token",
  mt_first_chunk: "MT 1st chunk",
  tts_request: "TTS request",
  tts_first_byte: "TTS 1st byte",
  audio_first_sent: "audio sent",
  tail_tts_first_byte: "last seg TTS 1st byte",
  first_audible: "first audible",
};

export function LatencyWaterfall({ turn }: { turn: TurnView }) {
  const commit = turn.browserMarks.commit_sent;
  if (commit === undefined) return null;
  const rows: { label: string; ms: number; est: boolean; head?: boolean }[] = [{ label: LABEL.commit_sent, ms: commit, est: false }];
  for (const m of SERVER_ORDER) if (turn.serverMarks[m] !== undefined) rows.push({ label: LABEL[m] ?? m, ms: commit + turn.serverMarks[m], est: true });
  if (turn.latencyMs !== undefined) rows.push({ label: LABEL.first_audible, ms: turn.latencyMs, est: false, head: true });
  const limit = LIMIT_MS[turn.mode];
  const scale = Math.max(limit, ...rows.map((r) => r.ms)) * 1.05;
  const pct = (ms: number) => `${Math.max(0, (ms / scale) * 100)}%`;
  const h = turn.latencyMs;
  const verdict = h === undefined ? "" : h <= TARGET_MS[turn.mode] ? "ok" : h <= limit ? "warn" : "bad";
  return (
    <div className="waterfall">
      {rows.map((r) => (
        <div key={r.label} className={`wf-row ${r.head ? `head ${verdict}` : ""}`}>
          <span className="wf-label">{r.label}{r.est ? "*" : ""}</span>
          <span className="wf-track">
            <span className="wf-bar" style={{ width: pct(r.ms) }} />
            <span className="wf-target" style={{ left: pct(TARGET_MS[turn.mode]) }} title="target" />
            <span className="wf-limit" style={{ left: pct(limit) }} title="limit" />
          </span>
          <span className="wf-ms">{Math.round(r.ms)} ms</span>
        </div>
      ))}
      <div className="wf-note">
        ms after speech end · <span className="lg-target">│ target {TARGET_MS[turn.mode]}</span> ·{" "}
        <span className="lg-limit">│ limit {limit}</span> · * server estimate
      </div>
    </div>
  );
}
