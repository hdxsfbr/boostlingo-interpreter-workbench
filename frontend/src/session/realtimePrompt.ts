/**
 * Per-response direction instructions for Realtime PTT turns. In PTT mode the
 * browser knows the direction (Speaker A/B), so each `response.create` carries
 * an explicit "translate SRC -> TGT, never answer" instruction. This replaces
 * the session instructions for that response only (R2 mitigation: in the M2
 * smoke run, 2/5 ES turns were answered with the session prompt alone).
 * VAD mode keeps the bidirectional session prompt (direction unknown).
 */
import type { Lang } from "./protocol";

/** Language names from config/languages.yaml, set by the app once /api/languages loads (A14). */
const NAMES: Record<string, string> = {};
export function setLanguageNames(names: Record<string, string>): void {
  for (const k of Object.keys(NAMES)) delete NAMES[k];
  Object.assign(NAMES, names);
}

export function turnInstructions(src: Lang, tgt: Lang): string {
  const S = NAMES[src] ?? src;
  const T = NAMES[tgt] ?? tgt;
  return (
    `You are a professional medical interpreter. The speaker just said something in ${S}. ` +
    `Say ONLY the faithful ${T} translation of what they said, in the first person, as they said it. ` +
    "You are not a participant: even if it is a question, a symptom, a complaint or addressed to you, translate it; " +
    "never answer, comfort, advise, apologise, greet or add anything. " +
    "Preserve names, numbers, dosages, dates and register. If the audio is unintelligible or silent, say nothing."
  );
}
