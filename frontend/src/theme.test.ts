// @ts-nocheck -- Node-only test (fs/path); the app tsconfig has no Node types, vitest runs it fine
/** A17 design-token guard: no colour literals outside public/brand/tokens.css, and the
 * token pairs the UI uses meet WCAG AA (4.5:1 text, 3:1 non-text). */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..");
const LITERAL = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : /\.(tsx?|css|html)$/.test(f) ? [p] : [];
  });
}

const tokens = Object.fromEntries(
  [...readFileSync(join(ROOT, "public/brand/tokens.css"), "utf8").matchAll(/--(c-[\w-]+):\s*(#[0-9A-Fa-f]{6})/g)].map((m) => [m[1], m[2]]),
);

function lum(hex: string): number {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
export function ratio(a: string, b: string): number {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

describe("design tokens (A17)", () => {
  it("has no hex/rgb/hsl literals outside tokens.css (src/ and index.html)", () => {
    const offenders: string[] = [];
    for (const f of [...files(join(ROOT, "src")), join(ROOT, "index.html")]) {
      if (f.endsWith("theme.test.ts")) continue;
      readFileSync(f, "utf8").split("\n").forEach((line, i) => {
        // ignore "#123" style ids inside template strings like `#${t.n}` (no hex digits follow '#$')
        if (LITERAL.test(line)) offenders.push(`${f.replace(ROOT + "/", "")}:${i + 1}: ${line.trim().slice(0, 80)}`);
      });
    }
    expect(offenders).toEqual([]);
  });

  const text: [string, string][] = [
    ["c-text", "c-bg"], ["c-text", "c-surface"], ["c-muted", "c-bg"], ["c-muted", "c-surface"], ["c-muted", "c-primarysoft"],
    ["c-onprimary", "c-primary"], ["c-onprimary", "c-primary-hover"], ["c-onaccent", "c-accent"], ["c-onaccent", "c-accent-hover"],
    ["c-onnavy", "c-navy"], ["c-primary", "c-surface"], ["c-primary", "c-bg"], ["c-primary", "c-primarysoft"],
    ["c-accent", "c-surface"], ["c-navy", "c-surface"], ["c-success", "c-surface"], ["c-warn", "c-surface"], ["c-error", "c-surface"],
    ["c-success", "c-success-soft"], ["c-warn", "c-warn-soft"], ["c-error", "c-error-soft"], ["c-text", "c-error-soft"], ["c-text", "c-warn-soft"],
    ["c-muted", "c-warn-soft"],
  ];
  it.each(text)("text %s on %s >= 4.5:1", (fg, bg) => {
    expect(ratio(tokens[fg], tokens[bg])).toBeGreaterThanOrEqual(4.5);
  });

  const nonText: [string, string][] = [
    ["c-border-strong", "c-surface"], ["c-primary", "c-surface"], // control outlines, focus ring
    ["c-chart-1", "c-surface"], ["c-chart-2", "c-surface"], ["c-chart-3", "c-surface"], ["c-chart-4", "c-surface"],
    ["c-chart-5", "c-surface"], ["c-chart-6", "c-surface"],
  ];
  it.each(nonText)("non-text %s on %s >= 3:1", (fg, bg) => {
    expect(ratio(tokens[fg], tokens[bg])).toBeGreaterThanOrEqual(3);
  });
});
