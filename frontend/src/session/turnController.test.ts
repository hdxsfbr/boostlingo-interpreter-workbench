import { describe, expect, it } from "vitest";
import { TurnController } from "./turnController";

describe("TurnController", () => {
  it("maps speakers to directions from the pair config", () => {
    const tc = new TurnController({ a: "en", b: "es" });
    expect(tc.directionFor("A")).toEqual({ src: "en", tgt: "es" });
    expect(tc.directionFor("B")).toEqual({ src: "es", tgt: "en" });
  });

  it("takes speech end from the last voiced frame, not the release", () => {
    const tc = new TurnController({ a: "en", b: "es" }, null);
    tc.pttDown("A", 0);
    tc.frame(true, 100);
    tc.frame(true, 120);
    tc.frame(false, 140);
    const end = tc.pttUp(400)!;
    expect(end.tSpeechEnd).toBe(120);
    expect(end.hadSpeech).toBe(true);
  });

  it("falls back to release time when nothing was voiced", () => {
    const tc = new TurnController({ a: "en", b: "es" });
    tc.pttDown("B", 0);
    tc.frame(false, 20);
    const end = tc.pttUp(50)!;
    expect(end.tSpeechEnd).toBe(50);
    expect(end.hadSpeech).toBe(false);
  });

  it("emits one pause commit per in-turn pause", () => {
    const tc = new TurnController({ a: "en", b: "es" }, 300);
    tc.pttDown("A", 0);
    expect(tc.frame(false, 10).pauseCommit).toBe(false); // no speech yet
    tc.frame(true, 100);
    expect(tc.frame(false, 300).pauseCommit).toBe(false);
    expect(tc.frame(false, 400).pauseCommit).toBe(true);
    expect(tc.frame(false, 500).pauseCommit).toBe(false);
    tc.frame(true, 600);
    expect(tc.frame(false, 920).pauseCommit).toBe(true);
  });

  it("does not send frames outside a turn and numbers turns", () => {
    const tc = new TurnController({ a: "en", b: "es" });
    expect(tc.frame(true, 0).send).toBe(false);
    expect(tc.pttDown("A", 0).id).toBe(1);
    tc.pttUp(1);
    expect(tc.pttDown("B", 2).id).toBe(2);
  });
});

describe("VadSegmenter (cascade VAD)", () => {
  const f = () => new Int16Array(480);
  it("debounces, replays pre-roll and ends after the silence window", async () => {
    const { VadSegmenter } = await import("./turnController");
    const v = new VadSegmenter(400, 5, 3);
    let t = 0;
    for (let i = 0; i < 10; i++) expect(v.frame(f(), false, (t += 20)).start).toBeNull();
    expect(v.frame(f(), true, (t += 20)).start).toBeNull(); // click: one voiced frame
    expect(v.frame(f(), false, (t += 20)).start).toBeNull();
    v.frame(f(), true, (t += 20));
    v.frame(f(), true, (t += 20));
    const a = v.frame(f(), true, (t += 20));
    expect(a.start?.length).toBe(5); // pre-roll capped, includes the debounce frames
    expect(v.active).toBe(true);
    const lastVoiced = t;
    let ended = -1;
    for (let i = 0; i < 30 && ended < 0; i++) if (v.frame(f(), false, (t += 20)).end) ended = t;
    expect(ended - lastVoiced).toBe(400);
    expect(v.active).toBe(false);
  });
});

describe("pause hint (speculative MT)", () => {
  it("fires once per pause, before the pause commit", () => {
    const tc = new TurnController({ a: "en", b: "es" }, 300, 150);
    tc.pttDown("A", 0);
    tc.frame(true, 20);
    const acts = [];
    for (let t = 40; t <= 400; t += 20) acts.push({ t, ...tc.frame(false, t) });
    const hint = acts.filter((a) => a.pauseHint);
    const commit = acts.filter((a) => a.pauseCommit);
    expect(hint.map((a) => a.t)).toEqual([180]);
    expect(commit.map((a) => a.t)).toEqual([320]);
    tc.frame(true, 420); // speech resumes: re-armed
    expect(tc.frame(false, 580).pauseHint).toBe(true);
  });
});
