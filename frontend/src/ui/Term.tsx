import { useId, type ReactNode } from "react";
import { definitionFor } from "./definitions";

/** A18: a label with a plain-language definition shown on hover AND keyboard focus.
 * The tooltip text is always in the DOM (visually hidden until shown) and linked with
 * aria-describedby, so screen readers get it too. */
export function Term({ k, text, className, children }: { k: string; text?: string; className?: string; children: ReactNode }) {
  const id = useId();
  const def = text ?? definitionFor(k);
  if (!def) return <>{children}</>;
  return (
    <span className={`term ${className ?? ""}`} tabIndex={0} aria-describedby={id} data-term={k}>
      {children}
      <span role="tooltip" id={id} className="tip">{def}</span>
    </span>
  );
}
