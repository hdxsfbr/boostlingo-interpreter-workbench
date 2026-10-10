import { describe, expect, it } from "vitest";
import { compare, describeError, fmtDur, summaryRows, type ProfileSummary } from "./api";

const prof = (name: string, h: number, chrf: number, usd: number, fail = 0): ProfileSummary => ({
  profile: name, n: 10, done: 10 - fail, H: { n: 10, p50: h, p90: h + 300 }, H_minus_gap: { n: 10, p50: h - 450, p90: h - 150 },
  tail: { n: 0, p50: null, p90: null }, quality: { "en->es": { chrF: chrf - 2, src_WER_mean: 0.01 }, "es->en": { chrF: chrf + 2, src_WER_mean: 0.02 }, all: { chrF: chrf } },
  cost: { usd_total: usd / 10, usd_per_min: usd }, failures: { count: fail },
});

describe("experiment helpers", () => {
  it("summaryRows maps the M5 results shape to the table columns", () => {
    const [r] = summaryRows({ summary: [prof("realtime", 1002, 78.6, 0.179)] });
    expect(r).toMatchObject({ setup: "realtime", H_p50: 1002, H_p90: 1302, Hgap_p50: 552, chrF_en_es: 76.6, chrF_es_en: 80.6, chrF_all: 78.6, WER_es: 0.02, usd_per_min: 0.179, failures: 0, tail_p50: null });
  });
  it("summaryRows uses the A21 headline (H_fair) when present; first audible is the literal H", () => {
    const p = { ...prof("cascade-openai", 545, 75, 0.049), H_fair: { n: 96, p50: 1744, p90: 2196 }, H_fair_minus_gap: { n: 96, p50: 1286, p90: 1742 } };
    const [r] = summaryRows({ summary: [p] });
    expect(r).toMatchObject({ H_p50: 1744, H_p90: 2196, Hgap_p50: 1286, firstAudible_p50: 545, firstAudible_p90: 845 });
  });
  it("compare lists every setup of either side with b - a deltas", () => {
    const a = { summary: [prof("realtime-mini", 1013, 77, 0.052), prof("cascade-openai", 545, 75, 0.049)] };
    const b = { summary: [prof("realtime-mini", 1100, 76, 0.05, 1)] };
    const rows = compare(a, b);
    const h = rows.find((r) => r.setup === "realtime-mini" && r.key === "H_p50")!;
    expect(h).toMatchObject({ a: 1013, b: 1100, delta: 87 });
    expect(rows.find((r) => r.setup === "realtime-mini" && r.key === "failures")!.delta).toBe(1);
    expect(rows.find((r) => r.setup === "cascade-openai" && r.key === "H_p50")).toMatchObject({ a: 545, b: null, delta: null });
  });
  it("describes FastAPI errors and formats durations", () => {
    expect(describeError([{ loc: ["body"], msg: "Value error, unknown setup(s) ['x']" }])).toBe("unknown setup(s) ['x']");
    expect(describeError({ code: "busy", message: "experiment e1 is running" })).toBe("experiment e1 is running");
    expect(fmtDur(45)).toBe("45 s");
    expect(fmtDur(125)).toBe("2 min 5 s");
  });
});
