import { earlyReason, isEarly, LIMIT_MS, stageMs, TARGET_MS } from "../store/metrics";
import type { TurnView } from "../store/reducer";
import { Term } from "./Term";

/** Per-turn waterfall (FR-7). Browser marks are exact (one clock). Server
 * stage marks are durations from the server receiving the commit; they are
 * placed after the browser's commit_sent mark and labelled as estimates.
 * A18: a stage that lands before speech end (speculative MT, or an earlier
 * segment) is shown as "early" with its magnitude, never as a negative bar. */
const SERVER_ORDER = ["stt_final", "mt_first_token", "mt_first_chunk", "tts_request", "tts_first_byte", "audio_first_sent", "tail_tts_first_byte"];
export const LABEL: Record<string, string> = {
  commit_sent: "commit sent",
  stt_final: "STT final",
  mt_first_token: "MT 1st token",
  mt_first_chunk: "MT 1st chunk",
  tts_request: "TTS request",
  tts_first_byte: "TTS 1st byte",
  audio_first_sent: "audio sent",
  tail_tts_first_byte: "last seg TTS 1st",
  first_audible: "first audible",
};

export const beforeSpeechEnd = (ms: number) =>
  Math.abs(ms) >= 1000 ? `${(Math.abs(ms) / 1000).toFixed(1)} s before speech end` : `${Math.round(Math.abs(ms))} ms before speech end`;

type Row = { key: string; ms: number; est: boolean; head?: boolean };

export function LatencyWaterfall({ turn }: { turn: TurnView }) {
  const commit = turn.browserMarks.commit_sent;
  if (commit === undefined) return null;
  const rows: Row[] = [{ key: "commit_sent", ms: commit, est: false }];
  for (const m of SERVER_ORDER) {
    const v = stageMs(turn, m);
    if (v !== undefined) rows.push({ key: m, ms: v, est: true });
  }
  if (turn.latencyMs !== undefined) rows.push({ key: "first_audible", ms: turn.latencyMs, est: false, head: true });
  const limit = LIMIT_MS[turn.mode];
  const scale = Math.max(limit, ...rows.map((r) => r.ms)) * 1.05;
  const pct = (ms: number) => `${Math.max(0, (ms / scale) * 100)}%`;
  const h = turn.latencyMs;
  const verdict = h === undefined ? "" : h <= TARGET_MS[turn.mode] ? "ok" : h <= limit ? "warn" : "bad";
  const why = earlyReason(turn);
  return (
    <div className="waterfall">
      {rows.map((r) => {
        const early = isEarly(r.ms);
        return (
          <div key={r.key} className={`wf-row ${r.head ? `head ${verdict}` : ""} ${early ? "early" : ""}`} data-testid={`wf-${r.key}`}>
            <span className="wf-label">
              <Term k={r.key}>{LABEL[r.key] ?? r.key}</Term>
              {r.est && <Term k="estimate">*</Term>}
            </span>
            {early ? (
              <span className="wf-track-early">
                <Term k="early" className="wf-early" text={`early (${why}) · ${beforeSpeechEnd(r.ms)}. Started while the speaker was still talking, so it is not drawn as a bar.`}>
                  early
                </Term>
              </span>
            ) : (
              <span className="wf-track">
                <span className="wf-bar" style={{ width: pct(r.ms) }} />
                <span className="wf-target" style={{ left: pct(TARGET_MS[turn.mode]) }} title="target" />
                <span className="wf-limit" style={{ left: pct(limit) }} title="limit" />
              </span>
            )}
            <span className={`wf-ms ${early ? "wf-ms-early" : ""}`}>{early ? `\u2212${Math.round(-r.ms)} ms` : `${Math.round(r.ms)} ms`}</span>
          </div>
        );
      })}
      <div className="wf-note">
        ms after speech end · <span className="lg-target">│ target {TARGET_MS[turn.mode]}</span> ·{" "}
        <span className="lg-limit">│ limit {limit}</span> · <Term k="estimate">*</Term> server estimate
      </div>
    </div>
  );
}
