/** Language pairs from GET /api/languages (config/languages.yaml; FR-5, DESIGN A14). */
export type PairInfo = { id: string; a: string; b: string; benchmarked: boolean; label: string };
export type LanguagesConfig = { default_pair: string; languages: Record<string, { name: string }>; pairs: PairInfo[] };

/** URL ?pair= may be a pair id or "a-b" in either order; unknown values fall back to the default pair. */
export function pickPair(cfg: LanguagesConfig, wanted: string | null): PairInfo {
  const def = cfg.pairs.find((p) => p.id === cfg.default_pair) ?? cfg.pairs[0];
  if (!wanted) return def;
  const byId = cfg.pairs.find((p) => p.id === wanted);
  if (byId) return byId;
  const [x, y] = wanted.split(/[-,]/);
  return cfg.pairs.find((p) => (p.a === x && p.b === y) || (p.a === y && p.b === x)) ?? def;
}

export const langName = (cfg: LanguagesConfig | null, code: string) => cfg?.languages[code]?.name ?? code;
export const langShort = (code: string) => code.toUpperCase();

export async function fetchLanguages(): Promise<LanguagesConfig> {
  const r = await fetch("/api/languages");
  if (!r.ok) throw new Error(`languages: HTTP ${r.status}`);
  return r.json() as Promise<LanguagesConfig>;
}
