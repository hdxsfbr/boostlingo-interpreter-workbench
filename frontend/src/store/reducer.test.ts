import { describe, expect, it } from "vitest";
import fixtures from "../../../contract/fixtures/server_events.json";
import { normalizeServerEvent } from "../session/transports/cascadeWs";
import type { ServerEvent, SessionEvent } from "../session/protocol";
import { initialState, joinSegments, reduce } from "./reducer";
import { quantile, summarize, toCsv, toRecord } from "./metrics";

const run = (evs: SessionEvent[]) => evs.reduce(reduce, initialState());
const started: SessionEvent = { type: "turn.started", turn_id: 1, src: "en", tgt: "es", speaker: "A", mode: "cascade", at: 0 };

describe("reducer", () => {
  it("replaces partials with finals and never regresses a final", () => {
    const s = run([
      started,
      { type: "transcript.partial", turn_id: 1, seg: 0, text: "Good" },
      { type: "transcript.final", turn_id: 1, seg: 0, text: "Good morning." },
      { type: "transcript.partial", turn_id: 1, seg: 0, text: "stale" },
      { type: "transcript.partial", turn_id: 1, seg: 1, text: "How" },
    ]);
    expect(joinSegments(s.turns[1].source)).toEqual([
      { text: "Good morning.", final: true },
      { text: "How", final: false },
    ]);
  });

  it("records the headline from the browser first_audible mark and settles the turn", () => {
    const s = run([
      started,
      { type: "speech.ended", turn_id: 1, t_speech_end: 1000 },
      { type: "latency.mark", turn_id: 1, mark: "stt_final", ms: 300, clock: "server" },
      { type: "audio.started", turn_id: 1, t_first_audible: 2600 },
      { type: "latency.mark", turn_id: 1, mark: "first_audible", ms: 1600, clock: "browser" },
      { type: "turn.done", turn_id: 1, usage: {} },
    ]);
    expect(s.turns[1].latencyMs).toBe(1600);
    expect(s.turns[1].status).toBe("playing");
    const s2 = reduce(s, { type: "audio.ended", turn_id: 1, at: 4000 });
    expect(s2.turns[1].status).toBe("done");
    expect(s2.turns[1].serverMarks.stt_final).toBe(300);
  });

  it("marks skipped turns and keeps a switch marker in the timeline", () => {
    const s = run([
      started,
      { type: "turn.skipped", turn_id: 1, reason: "empty_transcript" },
      { type: "mode.switched", from: "cascade", to: "realtime", at: 5 },
    ]);
    expect(s.turns[1].status).toBe("skipped");
    expect(s.timeline.map((i) => i.kind)).toEqual(["turn", "switch"]);
    expect(s.mode).toBe("realtime");
  });

  it("non-retryable turn errors fail the turn; errors are capped", () => {
    let s = run([started]);
    for (let i = 0; i < 8; i++) s = reduce(s, { type: "error", code: "x", stage: "mt", retryable: true, message: "m" });
    expect(s.errors.length).toBe(5);
    s = reduce(s, { type: "error", code: "timeout", stage: "tts", retryable: false, message: "m", turn_id: 1 });
    expect(s.turns[1].status).toBe("failed");
  });

  it("accepts every shared server fixture through the normaliser", () => {
    let s = run([started]);
    for (const raw of fixtures as ServerEvent[]) {
      const ev = normalizeServerEvent(raw);
      if (ev) s = reduce(s, ev);
    }
    expect(s.turns[1].serverMarks.tts_first_byte).toBeCloseTo(1010.2);
    expect(joinSegments(s.turns[1].target)[0].text).toBe("Buenos días, doctor.");
  });
});

describe("metrics", () => {
  it("computes median and p90 with interpolation", () => {
    const xs = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000];
    expect(quantile(xs, 0.5)).toBe(550);
    expect(quantile(xs, 0.9)).toBeCloseTo(910);
    expect(quantile([], 0.5)).toBeUndefined();
  });

  it("summarises per mode and exports CSV", () => {
    const s = run([
      started,
      { type: "speech.ended", turn_id: 1, t_speech_end: 0 },
      { type: "latency.mark", turn_id: 1, mark: "first_audible", ms: 1500, clock: "browser" },
      { type: "latency.mark", turn_id: 1, mark: "commit_sent", ms: 40, clock: "browser" },
      { type: "latency.mark", turn_id: 1, mark: "stt_final", ms: 250, clock: "server" },
      { type: "transcript.final", turn_id: 1, seg: 0, text: 'He said "hi", ok' },
    ]);
    const sum = summarize(Object.values(s.turns), "cascade");
    expect(sum.headline).toEqual({ n: 1, median: 1500, p90: 1500 });
    expect(sum.stages.stt_final.median).toBe(290); // A18: on the speech-end clock (commit 40 + 250)
    expect(summarize(Object.values(s.turns), "realtime").headline.n).toBe(0);
    const csv = toCsv([toRecord(s.turns[1])]);
    expect(csv.split("\n")[1]).toContain('"He said ""hi"", ok"');
  });
});
