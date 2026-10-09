import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { BrowserTurnRecorder, recordingPaths, SOURCE_TAIL_MS, TARGET_TAIL_MS, uploadUrl } from "./turnRecorder";
import { RecordToggle } from "../ui/Controls";
import { initialState, reduce } from "../store/reducer";
import { toRecord } from "../store/metrics";

class FakeMR {
  static all: FakeMR[] = [];
  state: "inactive" | "recording" = "inactive";
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(public stream: MediaStream, public opts: { mimeType: string }) {
    FakeMR.all.push(this);
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["x"]) });
    this.onstop?.();
  }
}

const fmt = { mime: "audio/webm;codecs=opus", ext: "webm" };
const streams = { source: { id: "mic" } as unknown as MediaStream, target: { id: "out" } as unknown as MediaStream };

describe("BrowserTurnRecorder (A11 realtime capture)", () => {
  beforeEach(() => {
    FakeMR.all = [];
    vi.stubGlobal("MediaRecorder", FakeMR);
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("records source until speech end and target until audio end, then uploads both", async () => {
    const up = vi.fn(async (_t: number, _s: string, _b: Blob, _m: string) => {});
    const rec = new BrowserTurnRecorder(streams, "sess-1", up, fmt);
    const paths = vi.fn();
    rec.onPaths = paths;
    rec.onEvent({ type: "turn.started", turn_id: 3, src: "en", tgt: "es", speaker: "A", mode: "realtime", at: 0 });
    expect(paths).toHaveBeenCalledWith(3, recordingPaths("sess-1", 3, "webm"));
    expect(FakeMR.all.map((m) => m.stream)).toEqual([streams.source, streams.target]);
    rec.onEvent({ type: "speech.ended", turn_id: 3, t_speech_end: 1 });
    vi.advanceTimersByTime(SOURCE_TAIL_MS);
    expect(up).toHaveBeenCalledTimes(1);
    expect(up.mock.calls[0].slice(0, 2)).toEqual([3, "source"]);
    rec.onEvent({ type: "audio.ended", turn_id: 3, at: 2 });
    vi.advanceTimersByTime(TARGET_TAIL_MS);
    expect(up.mock.calls.map((c) => c[1])).toEqual(["source", "target"]);
    expect(rec.active).toBe(0);
  });

  it("barge-in: a new turn ends the previous turn's target recording", () => {
    const up = vi.fn(async (_t: number, _s: string, _b: Blob, _m: string) => {});
    const rec = new BrowserTurnRecorder(streams, "s", up, fmt);
    rec.onEvent({ type: "turn.started", turn_id: 1, src: "en", tgt: "es", speaker: "A", mode: "realtime", at: 0 });
    rec.onEvent({ type: "speech.ended", turn_id: 1, t_speech_end: 1 });
    vi.advanceTimersByTime(SOURCE_TAIL_MS);
    rec.onEvent({ type: "turn.started", turn_id: 2, src: "es", tgt: "en", speaker: "B", mode: "realtime", at: 5 });
    expect(up.mock.calls.map((c) => [c[0], c[1]])).toEqual([[1, "source"], [1, "target"]]);
    expect(rec.active).toBe(2);
  });

  it("close() flushes everything still recording", async () => {
    vi.useRealTimers();
    const up = vi.fn(async (_t: number, _s: string, _b: Blob, _m: string) => {});
    const rec = new BrowserTurnRecorder(streams, "s", up, fmt);
    rec.onEvent({ type: "turn.started", turn_id: 1, src: "en", tgt: "es", speaker: "A", mode: "realtime", at: 0 });
    await rec.close();
    expect(up).toHaveBeenCalledTimes(2);
  });

  it("upload URL encodes the session id", () => {
    expect(uploadUrl("a/../b", 2, "target")).toBe("/api/recordings/a%2F..%2Fb/turns/2/target");
  });
});

describe("recording in the UI and turn record", () => {
  it("toggle is disabled when the server flag is off", () => {
    const html = renderToStaticMarkup(createElement(RecordToggle, { config: { enabled: false, retention_days: 30, max_upload_mb: 20 }, on: false, onToggle: () => {}, running: false }));
    expect(html).toMatch(/disabled=""/);
    expect(html).toContain("Disabled by server config");
  });
  it("toggle shows the consent notice when on", () => {
    const html = renderToStaticMarkup(createElement(RecordToggle, { config: { enabled: true, retention_days: 7, max_upload_mb: 20 }, on: true, onToggle: () => {}, running: false }));
    expect(html).not.toMatch(/disabled=""/);
    expect(html).toContain("for 7 days");
  });
  it("turn record carries the recording paths", () => {
    let s = initialState("realtime");
    s = reduce(s, { type: "turn.started", turn_id: 1, src: "en", tgt: "es", speaker: "A", mode: "realtime", at: 0 });
    s = reduce(s, { type: "turn.recording", turn_id: 1, recording: recordingPaths("sid", 1, "webm") });
    expect(toRecord(s.turns[1]).recording).toEqual({ source: "recordings/sid/turn-1-source.webm", target: "recordings/sid/turn-1-target.webm" });
    let c = initialState("cascade");
    c = reduce(c, { type: "turn.started", turn_id: 1, src: "en", tgt: "es", speaker: "A", mode: "cascade", at: 0 });
    c = reduce(c, { type: "turn.done", turn_id: 1, usage: {} });
    expect(toRecord(c.turns[1]).recording).toBeUndefined();
  });
});
