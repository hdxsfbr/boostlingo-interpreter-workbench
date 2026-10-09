import { describe, expect, it, vi } from "vitest";
import type { SessionEvent } from "../protocol";
import { CALLS_URL, MintError, RealtimeTransport, mintSecret } from "./realtimeWebrtc";
import { setLanguageNames } from "../realtimePrompt";

setLanguageNames({ en: "English", es: "Spanish" }); // normally loaded from /api/languages (A14)

class FakeTrack {
  enabled = true;
  readyState: "live" | "ended" = "live";
  kind = "audio";
  clones: FakeTrack[] = [];
  clone() {
    const c = new FakeTrack();
    this.clones.push(c);
    return c;
  }
  stop() {
    this.readyState = "ended";
  }
}

class FakeDC {
  readyState = "connecting";
  sent: Record<string, unknown>[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  send(s: string) {
    this.sent.push(JSON.parse(s));
  }
  close() {
    this.readyState = "closed";
  }
  serverSends(ev: object) {
    this.onmessage?.({ data: JSON.stringify(ev) });
  }
}

class FakePC {
  dc = new FakeDC();
  senders: { track: FakeTrack }[] = [];
  closed = false;
  connectionState = "new";
  ontrack: ((e: unknown) => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  addTrack(t: FakeTrack) {
    this.senders.push({ track: t });
  }
  getSenders() {
    return this.senders;
  }
  createDataChannel() {
    return this.dc;
  }
  async createOffer() {
    return { type: "offer", sdp: "v=0 offer" };
  }
  async setLocalDescription() {}
  async setRemoteDescription() {
    queueMicrotask(() => {
      this.dc.readyState = "open";
      this.dc.onopen?.();
    });
  }
  close() {
    this.closed = true;
  }
}

function setup(turnMode: "ptt" | "vad" = "ptt") {
  const mic = new FakeTrack();
  const pc = new FakePC();
  const events: SessionEvent[] = [];
  const remote = { attached: 0, detached: 0 };
  const fetchFn = vi.fn(async (url: string, init: RequestInit) => {
    if (url === "/api/realtime/session") {
      return new Response(JSON.stringify({ value: "ek_test", expires_at: 1, model: "gpt-realtime-mini", turn_mode: turnMode }), { status: 200 });
    }
    expect(url).toBe(CALLS_URL);
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer ek_test");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/sdp");
    return new Response("v=0 answer", { status: 201 });
  });
  const t = new RealtimeTransport({
    pair: { a: "en", b: "es" },
    micStream: { getAudioTracks: () => [mic] } as unknown as MediaStream,
    turnMode,
    emit: (e) => events.push(e),
    speechEnd: () => 0,
    onRemoteStream: () => remote.attached++,
    onRemoteGone: () => remote.detached++,
    onPlaying: () => {},
    fetchFn: fetchFn as unknown as typeof fetch,
    createPeer: () => pc as unknown as RTCPeerConnection,
  });
  return { t, pc, mic, events, remote, fetchFn };
}

describe("RealtimeTransport (WebRTC)", () => {
  it("mints, exchanges SDP with the ephemeral secret and reports ready", async () => {
    const { t, events, fetchFn } = setup();
    await t.connect();
    expect(fetchFn).toHaveBeenCalledTimes(2);
    const body = JSON.parse((fetchFn.mock.calls[0][1] as RequestInit).body as string);
    expect(body).toMatchObject({ a: "en", b: "es", turn_mode: "ptt" });
    expect(events[0]).toMatchObject({ type: "session.ready", mode: "realtime", pipeline: "webrtc" });
    expect(t.isOpen).toBe(true);
  });

  it("PTT: clear on press, commit + response.create on release, gate the uplink clone only", async () => {
    const { t, pc, mic } = setup();
    await t.connect();
    const uplink = mic.clones[0];
    expect(uplink.enabled).toBe(false); // idle: gated
    t.turnStart(1, "en", "es");
    expect(uplink.enabled).toBe(true);
    t.commit(1, false); // in-turn pause: ignored in realtime
    expect(pc.dc.sent.map((m) => m.type)).toEqual(["input_audio_buffer.clear"]);
    t.commit(1, true);
    expect(uplink.enabled).toBe(false);
    expect(mic.enabled).toBe(true); // local capture/VAD never gated
    expect(pc.dc.sent.map((m) => m.type)).toEqual(["input_audio_buffer.clear", "input_audio_buffer.commit", "response.create"]);
    const create = pc.dc.sent[2] as { response?: { instructions?: string } };
    expect(create.response?.instructions).toMatch(/in English\. Say ONLY the faithful Spanish translation/);
    t.cancel(1);
    expect(pc.dc.sent.slice(-2).map((m) => m.type)).toEqual(["response.cancel", "output_audio_buffer.clear"]);
  });

  it("VAD: the uplink is gated while the model is speaking", async () => {
    const { t, pc, mic } = setup("vad");
    await t.connect();
    const uplink = mic.clones[0];
    expect(uplink.enabled).toBe(true);
    t.vadTurn(1);
    pc.dc.serverSends({ type: "response.created", response: { id: "r1" } });
    pc.dc.serverSends({ type: "output_audio_buffer.started", response_id: "r1" });
    expect(uplink.enabled).toBe(false);
    pc.dc.serverSends({ type: "output_audio_buffer.stopped", response_id: "r1" });
    expect(uplink.enabled).toBe(true);
  });

  it("prunes history via conversation.item.delete after response.done", async () => {
    const { t, pc } = setup();
    await t.connect();
    for (const id of ["u1", "a1", "u2", "a2"]) pc.dc.serverSends({ type: "conversation.item.added", item: { id } });
    pc.dc.serverSends({ type: "response.done", response: { id: "x", status: "completed" } });
    expect(pc.dc.sent.filter((m) => m.type === "conversation.item.delete").map((m) => m.item_id)).toEqual(["u1", "a1"]);
  });

  it("close() releases the peer, data channel, uplink track and remote audio", async () => {
    const { t, pc, mic, remote } = setup();
    await t.connect();
    await t.close();
    expect(pc.closed).toBe(true);
    expect(pc.dc.readyState).toBe("closed");
    expect(mic.clones[0].readyState).toBe("ended");
    expect(mic.readyState).toBe("live"); // the session owns the mic itself
    expect(remote.detached).toBe(1);
    expect(t.liveResources).toEqual({ pc: false, dc: false, uplink: false });
  });

  it("surfaces mint rate limits with Retry-After", async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ detail: { code: "rate_limited", message: "slow down" } }), { status: 429, headers: { "Retry-After": "7" } }));
    const err = await mintSecret(f as unknown as typeof fetch, "/api/realtime/session", {}).catch((e) => e);
    expect(err).toBeInstanceOf(MintError);
    expect(err).toMatchObject({ status: 429, code: "rate_limited", retryAfter: 7 });
  });
});
