/** POSTs each finished turn record to /api/turns once (FR-10 JSONL log). */
import { useEffect, useRef } from "react";
import { toRecord } from "./metrics";
import type { State } from "./reducer";
import { SESSION_ID } from "../session/sessionId";

export function useTurnSink(state: State): void {
  const sent = useRef(new Set<number>());
  useEffect(() => {
    for (const t of Object.values(state.turns)) {
      if (sent.current.has(t.id) || !["done", "skipped", "failed"].includes(t.status)) continue;
      sent.current.add(t.id);
      void fetch("/api/turns", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: SESSION_ID, record: toRecord(t), user_agent: navigator.userAgent,
          // A20: context for optional server-side tracing (Langfuse); not written to the JSONL log
          meta: { providers: state.providers, pipeline: state.pipeline, pair: `${t.src}-${t.tgt}`,
                  harness: new URLSearchParams(location.search).get("source") === "file",
                  experiment: new URLSearchParams(location.search).get("exp") ?? undefined },
        }),
      }).catch(() => {});
    }
  }, [state.turns]);
}
