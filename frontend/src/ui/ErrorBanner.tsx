import type { SessionState } from "../session/protocol";
import type { ErrorView } from "../store/reducer";

const MIC_CODES = new Set(["mic_denied", "mic_missing", "mic_timeout", "mic_failed", "insecure_context"]);

export function ErrorBanner({ errors, onDismiss, onRetry, sessionState }: { errors: ErrorView[]; onDismiss(id: number): void; onRetry(): void; sessionState: SessionState }) {
  if (!errors.length) return null;
  return (
    <div className="errors">
      {errors.map((e) => (
        <div key={e.id} className={`error ${MIC_CODES.has(e.code) ? "blocking" : ""}`} role="alert" data-testid={`error-${e.code}`}>
          <span>
            <strong>{e.stage}</strong> · {e.message}
            {e.turn_id != null && <em> (turn {e.turn_id})</em>}
          </span>
          {(MIC_CODES.has(e.code) || e.code === "connect_failed") && sessionState !== "ready" && (
            <button onClick={() => { onDismiss(e.id); onRetry(); }}>Retry</button>
          )}
          <button className="x" onClick={() => onDismiss(e.id)} aria-label="dismiss">×</button>
        </div>
      ))}
    </div>
  );
}
