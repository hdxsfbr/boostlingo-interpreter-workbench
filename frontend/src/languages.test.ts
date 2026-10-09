import { describe, expect, it } from "vitest";
import { langName, pickPair, type LanguagesConfig } from "./languages";
import { setLanguageNames, turnInstructions } from "./session/realtimePrompt";

const CFG: LanguagesConfig = {
  default_pair: "en-es",
  languages: { en: { name: "English" }, es: { name: "Spanish" }, fr: { name: "French" } },
  pairs: [
    { id: "en-es", a: "en", b: "es", benchmarked: true, label: "English ↔ Spanish" },
    { id: "en-fr", a: "en", b: "fr", benchmarked: false, label: "English ↔ French" },
  ],
};

describe("language pair selection (A14)", () => {
  it("defaults to the configured default pair", () => {
    expect(pickPair(CFG, null).id).toBe("en-es");
    expect(pickPair(CFG, "de-en").id).toBe("en-es");
  });
  it("accepts a pair id or a-b in either order", () => {
    expect(pickPair(CFG, "en-fr").id).toBe("en-fr");
    expect(pickPair(CFG, "fr-en").id).toBe("en-fr");
    expect(pickPair(CFG, "es,en").id).toBe("en-es");
  });
  it("realtime turn instructions use configured names for both directions of both pairs", () => {
    setLanguageNames(Object.fromEntries(Object.entries(CFG.languages).map(([k, v]) => [k, v.name])));
    for (const [s, t] of [["en", "es"], ["es", "en"], ["en", "fr"], ["fr", "en"]]) {
      const txt = turnInstructions(s, t);
      expect(txt).toContain(`in ${langName(CFG, s)}.`);
      expect(txt).toContain(`faithful ${langName(CFG, t)} translation`);
    }
  });
});
