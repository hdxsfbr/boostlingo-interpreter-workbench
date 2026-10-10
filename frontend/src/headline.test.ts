/** A21: headline H = speech end -> first audio of the LAST sentence; first audible stays secondary. */
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { isSplit, responseMs, summarize, toRecord } from "./store/metrics";
import { initialState, type State, type TurnView } from "./store/reducer";
import { LatencyWaterfall } from "./ui/LatencyWaterfall";
import { MetricsSummary } from "./ui/MetricsSummary";

const seg = (text: string) => ({ text, final: true });
const mk = (id: number, segs: number, server: Record<string, number>, latency: number, mode = "cascade"): TurnView =>
  ({ id, mode, speaker: "A", src: "es", tgt: "en", status: "done", serverDone: true, audioEnded: true,
     source: {}, target: Object.fromEntries(Array.from({ length: segs }, (_, i) => [i, seg(`s${i}`)])),
     browserMarks: { commit_sent: 458, first_audible: latency }, serverMarks: server, latencyMs: latency }) as unknown as TurnView;

// measured es-m01 (2026-10-10): segment 0 held until the commit, heard at 510 ms; last segment audio ~1707 ms
const split = mk(12, 2, { mt_first_token: -7793.9, tts_first_byte: -6916, audio_first_sent: 1.2, stt_final: 650.2, tail_tts_first_byte: 1249 }, 510);
// single sentence: everything after the commit
const single = mk(2, 1, { stt_final: 600, mt_first_token: 700, tts_first_byte: 1050, audio_first_sent: 1060, tail_tts_first_byte: 592 }, 1737);
const rt = { ...mk(3, 1, {}, 1100, "realtime") } as TurnView;

describe("headline = first audio of the last sentence (A21)", () => {
  it("split turn: last segment's audio start, not the held first sentence", () => {
    expect(isSplit(split)).toBe(true);
    expect(responseMs(split)).toBeCloseTo(458 + 1249);
    expect(toRecord(split).latency_ms).toBe(510); // the literal first audible is still recorded
    expect(toRecord(split).response_ms).toBeCloseTo(1707);
  });
  it("single-segment and realtime turns: the measured first audible", () => {
    expect(isSplit(single)).toBe(false);
    expect(responseMs(single)).toBe(1737);
    expect(responseMs(rt)).toBe(1100);
  });
  it("summary headline uses responseMs, first audible is the second line", () => {
    const s = summarize([split, single], "cascade");
    expect(s.headline.median).toBeCloseTo((1707 + 1737) / 2);
    expect(s.firstAudible.median).toBeCloseTo((510 + 1737) / 2);
  });
  it("split card: 'last sentence audible*' is the headline row, first audible a secondary row", () => {
    const html = renderToStaticMarkup(h(LatencyWaterfall, { turn: split }));
    expect(html).toMatch(/class="wf-row head [a-z]+ *" data-testid="wf-last_sentence_audible"/);
    expect(html).toMatch(/class="wf-row  *" data-testid="wf-first_audible"/);
    expect(html).toContain("last sentence audible");
    expect(html).toMatch(/wf-last_sentence_audible.*?data-term="estimate"/);
    expect(html).toContain("1707 ms");
  });
  it("single card: first audible stays the headline, no last-sentence row", () => {
    const html = renderToStaticMarkup(h(LatencyWaterfall, { turn: single }));
    expect(html).toMatch(/class="wf-row head [a-z]+ *" data-testid="wf-first_audible"/);
    expect(html).not.toContain("wf-last_sentence_audible");
  });
  it("All-turns table: headline row + first-audible row", () => {
    const state = { ...initialState, mode: "cascade", turns: { 12: split, 2: single } } as unknown as State;
    const html = renderToStaticMarkup(h(MetricsSummary, { state }));
    expect(html).toContain("first audio of the last sentence");
    expect(html).toMatch(/data-testid="first-audible-cascade"><td>.*?<\/td><td>2<\/td><td>1124<\/td>/);
  });
});
