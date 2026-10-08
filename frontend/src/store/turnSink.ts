/** POSTs each finished turn record to /api/turns once (FR-10 JSONL log). */
import { useEffect, useRef } from "react";
import { toRecord } from "./metrics";
import type { State } from "./reducer";

const SESSION_ID = `${new Date().toISOString().replace(/[:.]/g, "-")}-${Math.random().toString(36).slice(2, 7)}`;

export function useTurnSink(state: State): void {
  const sent = useRef(new Set<number>());
  useEffect(() => {
    for (const t of Object.values(state.turns)) {
      if (sent.current.has(t.id) || !["done", "skipped", "failed"].includes(t.status)) continue;
      sent.current.add(t.id);
      void fetch("/api/turns", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: SESSION_ID, record: toRecord(t), user_agent: navigator.userAgent }),
      }).catch(() => {});
    }
  }, [state.turns]);
}
