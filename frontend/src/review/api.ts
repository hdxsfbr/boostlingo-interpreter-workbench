/** Typed client for /api/review (DESIGN A12). Errors carry the server's detail. */
export const DIMS = ["adequacy", "fluency", "naturalness"] as const;
export type Dim = (typeof DIMS)[number];
export type Scores = Record<Dim, number | null>;
export type Rating = Scores & { notes: string };
export type Progress = { done: number; total: number; complete: boolean };
export type SetSummary = { id: string; kind: "blind" | "session"; title: string; blind: boolean; items: number; progress?: Progress; revealed?: boolean };
export type ReviewItem = { item_id: string; idx: number; direction: string; source_text: string; reference: string; target_text: string; audio_url: string; variant?: string };
export type SetDetail = SetSummary & { rater: string; revealed: boolean; progress: Progress; items: ReviewItem[]; ratings: Record<string, Rating> };
export type SessionInfo = { session_id: string; turns: number; modes: string[]; set_id: string | null };
export type Stat = { n: number; mean: number | null; median: number | null; sd: number | null; min: number | null; max: number | null };
export type ResultRow = { variant: string; scope: string; n: number; composite_mean: number | null; m5?: { H_p50: number | null; H_p90: number | null; H_minus_gap_p50: number | null; chrF: number | null; usd_per_min: number | null } } & Record<Dim, Stat>;
export type Results = { set_id: string; raters: "me" | "all"; rater_count: number; rows: ResultRow[] };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
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
    let msg = `HTTP ${r.status}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* not json */
    }
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

const q = (o: Record<string, string>) => new URLSearchParams(o).toString();
const json = (method: string, body: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const reviewApi = {
  sets: (rater: string) => call<SetSummary[]>(`/api/review/sets?${q({ rater })}`),
  set: (id: string, rater: string) => call<SetDetail>(`/api/review/sets/${encodeURIComponent(id)}?${q({ rater })}`),
  save: (id: string, item: string, rater: string, r: Rating) =>
    call<{ saved: Rating; progress: Progress }>(`/api/review/sets/${encodeURIComponent(id)}/items/${encodeURIComponent(item)}/rating`, json("PUT", { rater, ...r })),
  reveal: (id: string, rater: string) => call<{ revealed: boolean }>(`/api/review/sets/${encodeURIComponent(id)}/reveal`, json("POST", { rater })),
  results: (id: string, rater: string, raters: "me" | "all") => call<Results>(`/api/review/sets/${encodeURIComponent(id)}/results?${q({ rater, raters })}`),
  resultsCsvUrl: (id: string, rater: string, raters: "me" | "all") => `/api/review/sets/${encodeURIComponent(id)}/results.csv?${q({ rater, raters })}`,
  ratingsCsvUrl: (id: string, rater: string) => `/api/review/sets/${encodeURIComponent(id)}/ratings.csv?${q({ rater })}`,
  sessions: () => call<SessionInfo[]>("/api/review/sessions"),
  importSession: (sid: string) => call<{ set_id: string }>(`/api/review/sessions/${encodeURIComponent(sid)}`, { method: "POST" }),
};
