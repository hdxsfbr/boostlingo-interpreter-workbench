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
