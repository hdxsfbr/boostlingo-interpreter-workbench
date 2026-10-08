import { describe, expect, it } from "vitest";
import { RenderClock } from "./clock";

describe("RenderClock", () => {
  it("uses the minimum receipt delay as the offset", () => {
    const c = new RenderClock(10);
    c.observe(1.0, 5000 + 1000 + 7); // 7 ms message delay
    c.observe(1.02, 5000 + 1020 + 2); // 2 ms delay (tightest)
    c.observe(1.04, 5000 + 1040 + 9);
    expect(c.toPerf(2.0)).toBeCloseTo(5000 + 2000 + 2, 6);
  });

  it("forgets old samples so drift is tracked", () => {
    const c = new RenderClock(2);
    c.observe(0, 100);
    c.observe(1, 1200);
    c.observe(2, 2200);
    expect(c.toPerf(3)).toBeCloseTo(3200, 6);
  });
});
