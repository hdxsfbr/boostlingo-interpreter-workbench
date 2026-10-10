/** A18: tooltips on every latency term; early (pre-speech-end) stages are never negative bars or p50 inputs. */
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { stageMs, summarize } from "./store/metrics";
import type { TurnView } from "./store/reducer";
import { definitionFor, DEFINITIONS } from "./ui/definitions";
import { beforeSpeechEnd, LABEL, LatencyWaterfall } from "./ui/LatencyWaterfall";
import { MetricsSummary } from "./ui/MetricsSummary";
import { Term } from "./ui/Term";
import { initialState, type State } from "./store/reducer";

const turn = (id: number, commit: number, server: Record<string, number>, latency: number): TurnView =>
  ({ id, mode: "cascade", speaker: "A", src: "en", tgt: "es", source: {}, target: {}, status: "done", serverDone: true, audioEnded: true,
     browserMarks: { commit_sent: commit, first_audible: latency }, serverMarks: server, latencyMs: latency }) as unknown as TurnView;

// speculative long turn: MT ran on a partial while the speaker was still talking, adopted at commit (spec_hit)
const spec = turn(1, 460, { spec_start: -5200, spec_hit: 90, stt_final: 420, mt_first_token: -4037, mt_first_chunk: -3900, tts_request: -3890, tts_first_byte: -2948, audio_first_sent: 300 }, 1495);
// ordinary short turn: everything after the commit
const plain = turn(2, 450, { stt_final: 600, mt_first_token: 700, mt_first_chunk: 800, tts_request: 810, tts_first_byte: 1050, audio_first_sent: 1060 }, 1560);

describe("latency definitions (A18)", () => {
  it.each(["commit sent", "STT final", "MT 1st token", "MT 1st chunk", "TTS request", "TTS 1st byte", "audio sent", "last seg TTS 1st", "first audible",
    "headline", "spec_start", "spec_hit", "tail_tts_first_byte", "p50", "p90", "n", "estimate", "stt_final", "mt_first_token", "tts_first_byte", "audio_first_sent", "early"])(
    "has a definition for %s", (k) => expect(definitionFor(k)?.length).toBeGreaterThan(20));
  it("covers every waterfall label", () => Object.values(LABEL).forEach((l) => expect(definitionFor(l)).toBeTruthy()));
  it("contains no colour literals in the shared map", () => expect(JSON.stringify(DEFINITIONS)).not.toMatch(/#[0-9a-f]{3,6}\b/i));

  it("Term is focusable and wired with aria-describedby to a role=tooltip", () => {
    const html = renderToStaticMarkup(h(Term, { k: "p50", children: "p50" }));
    const id = html.match(/aria-describedby="([^"]+)"/)?.[1];
    expect(html).toContain('tabindex="0"');
    expect(html).toContain(`role="tooltip" id="${id}"`);
    expect(html).toContain("half the turns were faster");
  });

  it("every row label and table header in the Latency card carries a tooltip", () => {
    const st: State = { ...initialState("cascade"), turns: { 1: spec, 2: plain } } as State;
    const html = renderToStaticMarkup(h(MetricsSummary, { state: st }));
    for (const k of ["commit_sent", "stt_final", "mt_first_token", "tts_first_byte", "first_audible", "estimate", "headline", "n", "p50", "p90", "spec_start", "spec_hit"])
      expect(html).toContain(`data-term="${k}"`);
  });
});

describe("early (speculative) stages (A18)", () => {
  it("are on the speech-end clock: commit_sent + server duration", () => {
    expect(stageMs(spec, "mt_first_token")).toBe(-3577);
    expect(stageMs(plain, "mt_first_token")).toBe(1150);
  });

  it("render as 'early (speculative) · 3.6 s before speech end', never a negative bar or number", () => {
    const html = renderToStaticMarkup(h(LatencyWaterfall, { turn: spec }));
    expect(html).toContain("early (speculative) · 3.6 s before speech end");
    expect(html).toContain("early (speculative) · 2.5 s before speech end"); // TTS 1st byte -2488
    expect(html).not.toMatch(/>-\d/);
    expect(html).toContain("1495 ms");
  });

  it("an early stage without spec_hit is an earlier segment", () => {
    const seg = turn(3, 400, { mt_first_token: -900 }, 1700);
    expect(renderToStaticMarkup(h(LatencyWaterfall, { turn: seg }))).toContain("early (earlier segment) · 500 ms before speech end");
    expect(beforeSpeechEnd(-3577)).toBe("3.6 s before speech end");
  });

  it("p50/p90 use only post-speech-end values; early turns are counted apart", () => {
    const s = summarize([spec, plain], "cascade");
    expect(s.stages.mt_first_token).toEqual({ n: 1, median: 1150, p90: 1150, early: 1 });
    expect(s.stages.stt_final).toMatchObject({ n: 2, early: 0 });
    expect(Object.values(s.stages).every((v) => v.median === undefined || v.median >= 0)).toBe(true);
    expect(s.headline).toEqual({ n: 2, median: 1527.5, p90: expect.any(Number) });
  });

  it("the headline can't be negative in the stats (a negative H is dropped, not averaged in)", () => {
    expect(summarize([turn(9, 400, {}, -20), plain], "cascade").headline.n).toBe(1);
  });
});
