/** Typed client + pure helpers for /api/experiments (DESIGN A13). */
export type SetupInfo = { name: string; label: string; mode: string; models: Record<string, string>; warning: string; unavailable: string; needs_confirmation_checkbox: boolean };
export type Utterance = { id: string; lang: string; size: string; text: string };
export type SetupsResponse = { setups: SetupInfo[]; default_setups: string[]; confirm_above_usd: number; utterances: Utterance[]; directions: { value: string; label: string }[] };
export type ExperimentConfig = { name: string; setups: string[]; utterances: "full" | "short" | "custom"; ids: string[]; directions: string; passes: number; allow_elevenlabs: boolean };
export type EstimateRow = { setup: string; utterances: number; source_min: number; usd_per_min: number | null; usd: number; duration_s: number; elevenlabs_chars?: number };
export type Estimate = { turns: number; per_setup: EstimateRow[]; usd: number; duration_s: number; pricing_as_of?: string; basis: string; confirm_above_usd: number; needs_confirmation: boolean; utterance_ids: string[] };
export type Stats = { n: number; p50: number | null; p90: number | null; p95?: number | null };
export type ProfileSummary = {
  profile: string; n: number; done: number; H: Stats; H_minus_gap: Stats; tail?: Stats; H_fair?: Stats; H_fair_minus_gap?: Stats;
  quality: Record<string, { chrF?: number | null; src_WER_mean?: number | null; n?: number }>;
  cost?: { usd_total?: number; usd_per_min?: number | null; source_min?: number };
  failures?: { count: number; rate?: number; reasons?: Record<string, number> };
};
export type Progress = { setup: string | null; setup_index: number; setups: number; utterance: string | null; done: number; total: number; failures: number; cost_usd: number; p50_H_ms: number | null; elapsed_s: number; cleanup?: { orphans: number } };
export type Experiment = {
  id: string; name: string; status: string; readonly: boolean; config: ExperimentConfig & Record<string, unknown>; estimate: Partial<Estimate>;
  created: number; started: number | null; finished: number | null; git_commit: string; models: Record<string, { models: Record<string, string>; reported_providers?: Record<string, string> }>;
  summary: ProfileSummary[]; cost_usd: number; error: string; progress: Partial<Progress>;
};
export type ExperimentListItem = Pick<Experiment, "id" | "name" | "status" | "readonly" | "created" | "cost_usd" | "git_commit" | "error"> & { setups: string[]; estimate_usd: number | null; progress: { done: number; total: number } | null };
export type Turn = { setup: string; n: number; utterance_id: string; lang: string; size: string; status: string; h_ms: number | null; h_minus_gap_ms: number | null; tail_ms: number | null; cost_usd: number; source: string; target: string };

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(url, init);
  } catch (e) {
    throw new ApiError(0, `network error: ${(e as Error).message}`);
  }
  if (!r.ok) {
    let detail: unknown = null;
    let msg = `HTTP ${r.status}`;
    try {
      detail = (await r.json()).detail;
      msg = describeError(detail) ?? msg;
    } catch {
      /* not json */
    }
    throw new ApiError(r.status, msg, detail);
  }
  return r.json() as Promise<T>;
}

/** FastAPI details: {code, message} or [{loc, msg}] (validation). */
export function describeError(detail: unknown): string | null {
  if (!detail) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => String((d as { msg?: string }).msg ?? JSON.stringify(d)).replace(/^Value error, /, "")).join("; ");
  const m = (detail as { message?: string }).message;
  return m ?? JSON.stringify(detail);
}

const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const expApi = {
  setups: () => call<SetupsResponse>("/api/experiments/setups"),
  estimate: (cfg: ExperimentConfig) => call<Estimate>("/api/experiments/estimate", post(cfg)),
  run: (cfg: ExperimentConfig, confirm: boolean) => call<Experiment>("/api/experiments", post({ ...cfg, confirm })),
  list: () => call<ExperimentListItem[]>("/api/experiments"),
  get: (id: string) => call<Experiment>(`/api/experiments/${encodeURIComponent(id)}`),
  turns: (id: string) => call<Turn[]>(`/api/experiments/${encodeURIComponent(id)}/turns`),
  cancel: (id: string) => call<Experiment>(`/api/experiments/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  running: () => call<{ id: string | null }>("/api/experiments/running"),
  eventsUrl: (id: string) => `/api/experiments/${encodeURIComponent(id)}/events`,
  exportUrl: (id: string, what: "json" | "summary" | "turns") =>
    what === "json" ? `/api/experiments/${encodeURIComponent(id)}/export.json` : `/api/experiments/${encodeURIComponent(id)}/export.csv?kind=${what}`,
};

// ----- pure helpers (unit-tested)
export type SummaryRow = {
  setup: string; n: number; done: number; H_p50: number | null; H_p90: number | null; Hgap_p50: number | null; Hgap_p90: number | null;
  firstAudible_p50: number | null; firstAudible_p90: number | null; tail_p50: number | null; chrF_en_es: number | null; chrF_es_en: number | null; chrF_all: number | null; WER_en: number | null; WER_es: number | null;
  usd_per_min: number | null; usd_total: number | null; failures: number;
};

export function summaryRows(e: Pick<Experiment, "summary">): SummaryRow[] {
  return e.summary.map((p) => ({
    // A21: headline H = first audio of the last sentence (H_fair); older summaries fall back to H
    setup: p.profile, n: p.n, done: p.done, H_p50: (p.H_fair ?? p.H).p50, H_p90: (p.H_fair ?? p.H).p90,
    Hgap_p50: (p.H_fair_minus_gap ?? p.H_minus_gap).p50, Hgap_p90: (p.H_fair_minus_gap ?? p.H_minus_gap).p90,
    firstAudible_p50: p.H.p50, firstAudible_p90: p.H.p90,
    tail_p50: p.tail?.p50 ?? null, chrF_en_es: p.quality["en->es"]?.chrF ?? null, chrF_es_en: p.quality["es->en"]?.chrF ?? null,
    chrF_all: p.quality.all?.chrF ?? null, WER_en: p.quality["en->es"]?.src_WER_mean ?? null, WER_es: p.quality["es->en"]?.src_WER_mean ?? null,
    usd_per_min: p.cost?.usd_per_min ?? null, usd_total: p.cost?.usd_total ?? null, failures: p.failures?.count ?? 0,
  }));
}

export const COMPARE_KEYS = ["H_p50", "H_p90", "Hgap_p50", "chrF_all", "WER_en", "WER_es", "usd_per_min", "failures"] as const;
export type CompareRow = { setup: string; key: (typeof COMPARE_KEYS)[number]; a: number | null; b: number | null; delta: number | null };

/** Side by side: every setup present in either experiment x the headline columns; delta = b - a. */
export function compare(a: Pick<Experiment, "summary">, b: Pick<Experiment, "summary">): CompareRow[] {
  const ra = Object.fromEntries(summaryRows(a).map((r) => [r.setup, r]));
  const rb = Object.fromEntries(summaryRows(b).map((r) => [r.setup, r]));
  const setups = [...new Set([...Object.keys(ra), ...Object.keys(rb)])];
  return setups.flatMap((s) =>
    COMPARE_KEYS.map((key) => {
      const va = (ra[s]?.[key] as number | null | undefined) ?? null;
      const vb = (rb[s]?.[key] as number | null | undefined) ?? null;
      return { setup: s, key, a: va, b: vb, delta: va != null && vb != null ? Math.round((vb - va) * 1000) / 1000 : null };
    }),
  );
}

export const fmtUsd = (v: number | null | undefined, d = 3) => (v == null ? "–" : `$${v.toFixed(d)}`);
export const fmtNum = (v: number | null | undefined, d = 0) => (v == null ? "–" : v.toFixed(d));
export const fmtDur = (s: number | null | undefined) => (s == null ? "–" : s < 90 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`);
