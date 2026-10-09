import { afterEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReviewItem, SetDetail } from "./api";
import { ApiError, reviewApi } from "./api";
import { applyKey, EMPTY, fmtStat, isComplete, resumeIndex } from "./rateLogic";
import { RateView } from "./RateView";

const item = (id: string): ReviewItem => ({ item_id: id, idx: 0, direction: "en->es", source_text: "Hi", reference: "Hola", target_text: "", audio_url: `/a/${id}` });

describe("rating keyboard", () => {
  it("1-5 scores the focused row and advances; stays on the last row", () => {
    let d = { cur: EMPTY, focus: 0 };
    for (const k of ["5", "4", "3"]) d = applyKey(d, k).draft;
    expect(d.cur).toMatchObject({ adequacy: 5, fluency: 4, naturalness: 3 });
    expect(d.focus).toBe(2);
    d = applyKey(d, "2").draft;
    expect(d.cur.naturalness).toBe(2);
  });
  it("Tab cycles rows (Shift+Tab backwards); Space plays; Enter saves; other keys pass through", () => {
    const d = { cur: EMPTY, focus: 2 };
    expect(applyKey(d, "Tab").draft.focus).toBe(0);
    expect(applyKey(d, "Tab", true).draft.focus).toBe(1);
    expect(applyKey(d, " ").action).toBe("toggle-play");
    expect(applyKey(d, "Enter").action).toBe("save-next");
    expect(applyKey(d, "6").handled).toBe(false);
    expect(applyKey(d, "a").handled).toBe(false);
  });
});

describe("resume", () => {
  it("opens at the first item without all three scores", () => {
    const items = [item("a"), item("b"), item("c")];
    expect(resumeIndex(items, { a: { adequacy: 5, fluency: 5, naturalness: 5, notes: "" }, b: { ...EMPTY, adequacy: 4 } })).toBe(1);
    const full = { adequacy: 5, fluency: 5, naturalness: 5, notes: "" };
    expect(resumeIndex(items, { a: full, b: full, c: full })).toBe(0);
    expect(isComplete({ ...full, fluency: null })).toBe(false);
  });
});

describe("results formatting", () => {
  it("matches results.md cells", () => {
    expect(fmtStat({ mean: 4.83, median: 5, sd: 0.39, min: 4, max: 5 })).toBe("4.83 / 5 (0.39, 4-5)");
    expect(fmtStat({ mean: 4.5, median: 4.5, sd: 0.55, min: 4, max: 5 })).toBe("4.50 / 4.5 (0.55, 4-5)");
    expect(fmtStat({ mean: null, median: null, sd: null, min: null, max: null })).toBe("–");
  });
});

describe("rate view", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("renders the current clip without any variant when blind", () => {
    const set = { id: "blind-m5", kind: "blind", title: "t", blind: true, items: [item("clip_001.ogg")], rater: "x", revealed: false,
      progress: { done: 0, total: 1, complete: false }, ratings: {} } as unknown as SetDetail;
    const html = renderToStaticMarkup(createElement(RateView, { set, rater: "x", onChanged: () => {}, onDone: () => {} }));
    expect(html.replace(/<!-- -->/g, "")).toContain('data-testid="rate-pos">1 of 1<');
    expect(html).toContain("Hola");
    expect(html).not.toContain("variant");
  });
  it("save errors surface the server detail", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "adequacy must be an integer 1-5 or empty" }), { status: 400 })));
    await expect(reviewApi.save("s", "i", "x", EMPTY)).rejects.toEqual(new ApiError(400, "adequacy must be an integer 1-5 or empty"));
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(reviewApi.save("s", "i", "x", EMPTY)).rejects.toMatchObject({ status: 0 });
  });
});
