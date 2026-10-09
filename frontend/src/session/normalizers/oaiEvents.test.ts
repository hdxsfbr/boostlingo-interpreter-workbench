import { describe, expect, it } from "vitest";
import recorded from "../../../../contract/fixtures/openai/realtime_ws_two_turns.json";
import recordedRtc from "../../../../contract/fixtures/openai/realtime_webrtc_three_turns.json";
import type { SessionEvent } from "../protocol";
import { HistoryPruner, OaiNormalizer, type OaiEvent } from "./oaiEvents";

function setup() {
  const out: SessionEvent[] = [];
  let t = 1000;
  const audio: [number, boolean][] = [];
  const n = new OaiNormalizer({
    emit: (e) => out.push(e),
    now: () => (t += 10),
    speechEnd: (id) => ({ 1: 900, 2: 5000 } as Record<number, number>)[id],
    onOutputAudio: (id, p) => audio.push([id, p]),
  });
  return { n, out, audio };
}

const events = recorded as OaiEvent[];

describe("OaiNormalizer on a recorded two-turn session", () => {
  it("maps transcripts and translations to the committed turns", () => {
    const { n, out } = setup();
    // replay turn by turn: commit 1 before the first committed event, 2 before the second
    let commits = 0;
    for (const ev of events) {
      if (ev.type === "input_audio_buffer.committed") n.turnCommitted(++commits);
      n.handle(ev);
    }
    const finals = out.filter((e) => e.type === "translation.final") as { turn_id: number; text: string }[];
    expect(finals.map((f) => [f.turn_id, f.text])).toEqual([
      [1, "He tenido un dolor de cabeza durante tres días."],
      [2, "It hurts in my chest when I take a deep breath."],
    ]);
    const src = out.filter((e) => e.type === "transcript.final") as { turn_id: number; text: string }[];
    expect(src[0]).toMatchObject({ turn_id: 1, text: "I have had a headache for three days." });
    const done = out.filter((e) => e.type === "turn.done").map((e) => e.turn_id);
    expect(done).toEqual([1, 2]);
    const marks = out.filter((e) => e.type === "latency.mark" && e.turn_id === 1).map((e) => (e as { mark: string }).mark);
    expect(marks).toEqual(expect.arrayContaining(["response_created", "output_transcript_first", "output_audio_first_delta"]));
    // marks are relative to speech end and only emitted once per turn
    expect(new Set(marks).size).toBe(marks.length);
  });

  it("drives gating and audio.ended from the WebRTC output buffer events", () => {
    const { n, out, audio } = setup();
    n.turnCommitted(1);
    n.handle({ type: "response.created", response: { id: "r1" } });
    n.handle({ type: "output_audio_buffer.started", response_id: "r1" });
    n.handle({ type: "output_audio_buffer.stopped", response_id: "r1" });
    expect(audio).toEqual([[1, true], [1, false]]);
    expect(out.some((e) => e.type === "audio.ended" && e.turn_id === 1)).toBe(true);
    n.handle({ type: "response.done", response: { id: "r1", status: "completed", usage: { total_tokens: 3 } } });
    expect(out.at(-1)).toMatchObject({ type: "turn.done", turn_id: 1 });
  });

  it("ends earlier turns when the shared output buffer stops for a later one (VAD back-to-back)", () => {
    const { n, out } = setup();
    n.turnCommitted(1);
    n.handle({ type: "response.created", response: { id: "r1" } });
    n.handle({ type: "output_audio_buffer.started", response_id: "r1" });
    n.turnCommitted(2);
    n.handle({ type: "response.created", response: { id: "r2" } });
    n.handle({ type: "output_audio_buffer.started", response_id: "r2" });
    n.handle({ type: "output_audio_buffer.stopped", response_id: "r2" });
    const ended = out.filter((e) => e.type === "audio.ended").map((e) => e.turn_id);
    expect(ended).toEqual([1, 2]);
  });

  it("reports cancelled, failed, silent responses and empty commits", () => {
    const { n, out } = setup();
    n.turnCommitted(1);
    n.handle({ type: "response.created", response: { id: "a" } });
    n.handle({ type: "response.done", response: { id: "a", status: "cancelled" } });
    n.turnCommitted(2);
    n.handle({ type: "response.created", response: { id: "b" } });
    n.handle({ type: "response.done", response: { id: "b", status: "failed", status_details: { error: { code: "server_error", message: "x" } } } });
    n.turnCommitted(3);
    n.handle({ type: "response.created", response: { id: "c" } });
    n.handle({ type: "response.done", response: { id: "c", status: "completed" } });
    n.turnCommitted(4);
    n.handle({ type: "error", error: { code: "input_audio_buffer_commit_empty", message: "too small" } });
    n.handle({ type: "error", error: { code: "response_cancel_not_active" } });
    n.handle({ type: "error", error: { type: "tokens", code: "rate_limit_exceeded", message: "slow" } });
    expect(out.filter((e) => e.type !== "latency.mark").map((e) => [e.type, (e as { reason?: string; code?: string }).reason ?? (e as { code?: string }).code])).toEqual([
      ["turn.skipped", "cancelled"],
      ["error", "server_error"],
      ["turn.skipped", "no_output"],
      ["turn.skipped", "empty_audio"],
      ["error", "rate_limited"],
    ]);
  });
});

describe("OaiNormalizer on recorded WebRTC data-channel events (headless Chrome, 3 PTT turns)", () => {
  it("binds each response to its turn and drives playback state from output_audio_buffer", () => {
    const { n, out, audio } = setup();
    let commits = 0;
    for (const ev of recordedRtc as OaiEvent[]) {
      if (ev.type === "input_audio_buffer.committed") n.turnCommitted(++commits);
      n.handle(ev);
    }
    expect(out.filter((e) => e.type === "turn.done").map((e) => e.turn_id)).toEqual([1, 2, 3]);
    expect(out.filter((e) => e.type === "audio.ended").map((e) => e.turn_id)).toEqual([1, 2, 3]);
    expect(audio).toEqual([[1, true], [1, false], [2, true], [2, false], [3, true], [3, false]]);
    const tr = out.filter((e) => e.type === "translation.final") as { turn_id: number; text: string }[];
    expect(tr.every((t) => t.text.startsWith("He tenido un dolor de cabeza"))).toBe(true);
    expect(out.some((e) => e.type === "error" || e.type === "turn.skipped")).toBe(false);
  });

  it("the live session pruned to the last turn (server confirmed the deletes)", () => {
    const deleted = (recordedRtc as OaiEvent[]).filter((e) => e.type === "conversation.item.deleted");
    expect(deleted.length).toBe(4); // turn 1 after turn 2, turn 2 after turn 3
  });
});

describe("HistoryPruner", () => {
  it("keeps only the newest two items after each response", () => {
    const p = new HistoryPruner(2);
    const add = (id: string) => p.observe({ type: "conversation.item.added", item: { id } });
    add("u1");
    add("a1");
    expect(p.observe({ type: "response.done" })).toEqual([]);
    add("u2");
    add("a2");
    expect(p.observe({ type: "response.done" })).toEqual(["u1", "a1"]);
    add("u3");
    p.observe({ type: "conversation.item.deleted", item_id: "u3" });
    expect(p.observe({ type: "response.done" })).toEqual([]);
  });

  it("prunes the recorded session down to the last turn", () => {
    const p = new HistoryPruner(2);
    const dropped = (recorded as OaiEvent[]).flatMap((e) => p.observe(e));
    expect(dropped.length).toBe(2); // turn 1's user + assistant items after turn 2
  });
});
