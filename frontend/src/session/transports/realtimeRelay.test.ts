import { afterEach, describe, expect, it, vi } from "vitest";
import type { SessionEvent } from "../protocol";
import { RealtimeRelayTransport } from "./realtimeRelay";
import { setLanguageNames } from "../realtimePrompt";

setLanguageNames({ en: "English", es: "Spanish" }); // normally loaded from /api/languages (A14)

class FakeWS {
  static OPEN = 1;
  static last: FakeWS;
  readyState = 0;
  binaryType = "";
  sent: (string | Int16Array)[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string) {
    FakeWS.last = this;
    queueMicrotask(() => {
      this.readyState = 1;
      this.onopen?.();
    });
  }
  send(d: string | Int16Array) {
    this.sent.push(d);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  json(ev: object) {
    this.onmessage?.({ data: JSON.stringify(ev) });
  }
}

afterEach(() => vi.unstubAllGlobals());

function frame(idx: number, samples: number[]): ArrayBuffer {
  const buf = new ArrayBuffer(4 + samples.length * 2);
  new DataView(buf).setUint32(0, idx, true);
  new Int16Array(buf, 4).set(samples);
  return buf;
}

describe("RealtimeRelayTransport", () => {
  it("starts the relay, routes audio by response and closes cleanly", async () => {
    vi.stubGlobal("WebSocket", FakeWS);
    const events: SessionEvent[] = [];
    const audio: [number, number][] = [];
    const t = new RealtimeRelayTransport({
      url: "ws://x/ws/realtime",
      pair: { a: "en", b: "es" },
      emit: (e) => events.push(e),
      speechEnd: () => 0,
      onAudio: (turn, pcm) => audio.push([turn, pcm.length]),
    });
    const p = t.connect();
    await Promise.resolve();
    const ws = FakeWS.last;
    expect(JSON.parse(ws.sent[0] as string)).toMatchObject({ type: "relay.start", a: "en", b: "es", turn_mode: "ptt" });
    ws.json({ type: "relay.ready", model: "gpt-realtime-mini" });
    await p;
    expect(events[0]).toMatchObject({ type: "session.ready", pipeline: "relay" });

    t.turnStart(7, "es", "en");
    t.commit(7, true);
    const sent = ws.sent.slice(1).map((s) => JSON.parse(s as string).event);
    expect(sent.map((e) => e.type)).toEqual(["input_audio_buffer.clear", "input_audio_buffer.commit", "response.create"]);
    expect(sent[2].response.instructions).toMatch(/in Spanish\. Say ONLY the faithful English translation/);

    ws.json({ type: "response.created", response: { id: "r1" } });
    ws.onmessage?.({ data: frame(1, [1, 2, 3]) });
    ws.onmessage?.({ data: frame(9, [1]) }); // unknown response: dropped
    expect(audio).toEqual([[7, 3]]);
    t.cancel(7); // barge-in: late frames of the cancelled turn are dropped
    ws.onmessage?.({ data: frame(1, [4, 5]) });
    expect(audio).toEqual([[7, 3]]);

    await t.close();
    expect(ws.readyState).toBe(3);
    expect(t.liveResources).toEqual({ ws: false });
    expect(events.some((e) => e.type === "error")).toBe(false); // intentional close is silent
  });

  it("rejects connect on a relay error before ready", async () => {
    vi.stubGlobal("WebSocket", FakeWS);
    const events: SessionEvent[] = [];
    const t = new RealtimeRelayTransport({ url: "ws://x", pair: { a: "en", b: "es" }, emit: (e) => events.push(e), speechEnd: () => 0, onAudio: () => {} });
    const p = t.connect();
    await Promise.resolve();
    FakeWS.last.json({ type: "error", code: "rate_limited", stage: "realtime", retryable: true, message: "slow down" });
    await expect(p).rejects.toThrow("slow down");
    expect(events[0]).toMatchObject({ type: "error", code: "rate_limited", retryable: true });
  });
});
