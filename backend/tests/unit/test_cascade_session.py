"""Orchestrator tests with scripted fake providers (CQ-3.1 / CQ-3.3)."""
import asyncio

import pytest

from app.cascade.session import CascadeSession, Timeouts, is_empty_text
from app.core.errors import AuthError, RateLimited
from app.providers.fakes import FakeSTT, FakeTranslator, FakeTTS

FRAME = b"\x10\x00" * 480


class Sink:
    def __init__(self):
        self.events, self.audio = [], []

    async def event(self, ev):
        self.events.append(ev.model_dump())

    async def send_audio(self, turn_id, pcm):
        self.audio.append((turn_id, pcm))

    def types(self):
        return [e["type"] for e in self.events]

    def of(self, typ):
        return [e for e in self.events if e["type"] == typ]

    def marks(self):
        return {e["mark"]: e["ms"] for e in self.of("latency.mark")}


def make(stt=None, mt=None, tts=None, timeouts=None):
    sink = Sink()
    s = CascadeSession(stt or FakeSTT(), mt or FakeTranslator(), tts or FakeTTS(), send_event=sink.event,
                       send_audio=sink.send_audio, voices={"es": "marin"}, timeouts=timeouts or Timeouts())
    return s, sink


async def speak(s, turn_id=1, frames=5, commits=(True,), src="en", tgt="es"):
    await s.turn_start(turn_id, src, tgt)
    for final in commits:
        for _ in range(frames):
            s.audio(FRAME)
        await s.commit(turn_id, final)


async def finish(s, turn_id=1, timeout=2.0):
    t = s._turns.get(turn_id)
    if t and t.task:
        await asyncio.wait_for(asyncio.shield(t.task), timeout)
    await asyncio.sleep(0.02)


async def test_happy_path_streams_transcripts_translation_audio_and_marks():
    mt = FakeTranslator({"Good morning, doctor.": "Buenos días, doctor."})
    s, sink = make(mt=mt)
    await s.open()
    await speak(s)
    await finish(s)
    t = sink.types()
    assert t[0] == "turn.started"
    assert t.index("transcript.partial") < t.index("transcript.final") < t.index("translation.final")
    assert sink.of("translation.final")[0]["text"] == "Buenos días, doctor."
    assert sink.audio and all(tid == 1 for tid, _ in sink.audio)
    done = sink.of("turn.done")[0]
    for m in ("stt_final", "mt_first_token", "mt_first_chunk", "tts_request", "tts_first_byte", "audio_first_sent"):
        assert m in done["marks"], m
    m = done["marks"]
    assert m["stt_final"] <= m["mt_first_token"] <= m["tts_first_byte"] <= m["audio_first_sent"]
    assert done["usage"]["tts_chars"] == len("Buenos días, doctor.")
    assert done["usage"]["stt_audio_s"] == pytest.approx(5 * 960 / 48000)
    assert mt.calls[0][1:3] == ("en", "es")


async def test_segments_pipeline_but_audio_stays_in_segment_order():
    # seg 0 translates slowly, seg 1 fast: audio must still be seg0 chunks then seg1 chunks
    stt = FakeSTT(["First part of the sentence, please.", "Second part."])
    slow_first = {"First part of the sentence, please.": "Primera parte de la frase, por favor."}

    class SkewedMT(FakeTranslator):
        async def stream(self, text, src, tgt, ctx):
            self.ttft = 0.15 if text.startswith("First") else 0.0
            async for x in super().stream(text, src, tgt, ctx):
                yield x

    tts = FakeTTS(first_byte=0.0)
    s, sink = make(stt=stt, mt=SkewedMT(slow_first), tts=tts)
    await speak(s, commits=(False, True))
    await finish(s)
    order = [pcm[0] for _, pcm in sink.audio]
    idx_second = tts.chunks.index("SECOND PART.")
    seg0 = {i for i, c in enumerate(tts.chunks) if i != idx_second}
    assert idx_second < max(seg0)  # seg 1 was synthesised BEFORE seg 0 finished (pipelined) ...
    first_positions = [i for i, b in enumerate(order) if b in seg0]
    second_positions = [i for i, b in enumerate(order) if b == idx_second]
    assert max(first_positions) < min(second_positions)  # ... yet seg 0 audio is sent first
    assert [e["seg"] for e in sink.of("transcript.final")] == [0, 1]


async def test_audio_is_held_until_the_final_commit():
    s, sink = make(stt=FakeSTT(["Early segment here."]))
    await s.turn_start(1, "en", "es")
    s.audio(FRAME)
    await s.commit(1, False)  # in-turn pause: segment 0 translated + synthesised early
    await asyncio.sleep(0.1)
    assert sink.of("translation.final")  # pipelined work happened
    assert sink.audio == []  # but nothing played before speech end
    s.audio(FRAME)
    await s.commit(1, True)
    await finish(s)
    assert sink.audio
    # marks recorded before the final commit are reported relative to it (negative)
    assert sink.of("turn.done")[0]["marks"]["mt_first_token"] < 0


async def test_chunks_pipeline_into_tts_before_translation_finishes():
    text = "Primera frase completa. Segunda frase completa. Tercera frase completa."
    mt = FakeTranslator({"Good morning, doctor.": text}, token_delay=0.02)
    tts = FakeTTS(first_byte=0.0)
    s, sink = make(mt=mt, tts=tts)
    await speak(s)
    await finish(s)
    assert tts.chunks == ["Primera frase completa.", "Segunda frase completa.", "Tercera frase completa."]
    m = sink.of("turn.done")[0]["marks"]
    assert m["tts_first_byte"] < max(e["ms"] for e in sink.of("latency.mark") if e["mark"] == "stt_final") + 200


async def test_empty_transcript_skips_turn_without_mt_or_tts():
    mt, tts = FakeTranslator(), FakeTTS()
    s, sink = make(stt=FakeSTT(["  ...  "]), mt=mt, tts=tts)
    await speak(s)
    await finish(s)
    assert sink.of("turn.skipped")[0]["reason"] == "empty_transcript"
    assert mt.calls == [] and tts.chunks == [] and sink.audio == []
    assert is_empty_text("¿?") and not is_empty_text("sí")


async def test_empty_translation_skips_turn():
    s, sink = make(mt=FakeTranslator({"Good morning, doctor.": ""}))
    await speak(s)
    await finish(s)
    assert sink.of("turn.skipped")[0]["reason"] == "empty_translation"


async def test_rate_limit_is_retried_and_reported_then_succeeds():
    mt = FakeTranslator(failures=[RateLimited("429", retry_after=0.0)])
    s, sink = make(mt=mt)
    await speak(s)
    await finish(s)
    errs = sink.of("error")
    assert errs and errs[0]["code"] == "rate_limited" and errs[0]["retryable"] is True
    assert sink.of("turn.done")


async def test_auth_error_fails_turn_with_stage_and_session_survives():
    s, sink = make(mt=FakeTranslator(failures=[AuthError("bad key")]))
    await speak(s, turn_id=1)
    await finish(s, 1)
    err = sink.of("error")[0]
    assert (err["code"], err["stage"], err["retryable"], err["turn_id"]) == ("auth_error", "mt", False, 1)
    assert not sink.of("turn.done")
    await speak(s, turn_id=2)  # next turn unaffected
    await finish(s, 2)
    assert sink.of("turn.done")[0]["turn_id"] == 2


async def test_mid_stream_failure_is_not_retried():
    mt = FakeTranslator(fail_mid_stream=RateLimited("429 mid-stream"))
    s, sink = make(mt=mt)
    await speak(s)
    await finish(s)
    assert len(mt.calls) == 1
    assert sink.of("error")[0]["retryable"] is False


async def test_stt_final_watchdog_times_out():
    s, sink = make(stt=FakeSTT(hang_after_commit=True), timeouts=Timeouts(stt_final=0.1))
    await speak(s)
    await finish(s)
    err = sink.of("error")[0]
    assert err["code"] == "timeout" and err["stage"] == "stt"


async def test_mt_first_token_timeout():
    s, sink = make(mt=FakeTranslator(ttft=1.0), timeouts=Timeouts(mt_first_token=0.05))
    await speak(s)
    await finish(s)
    assert (sink.of("error")[0]["code"], sink.of("error")[0]["stage"]) == ("timeout", "mt")


async def test_tts_first_byte_timeout():
    s, sink = make(tts=FakeTTS(first_byte=1.0), timeouts=Timeouts(tts_first_byte=0.05))
    await speak(s)
    await finish(s)
    assert (sink.of("error")[0]["code"], sink.of("error")[0]["stage"]) == ("timeout", "tts")


async def test_cancel_tears_down_all_tasks():
    before = len(asyncio.all_tasks())
    s, sink = make(mt=FakeTranslator(ttft=0.5))
    await speak(s)
    await asyncio.sleep(0.05)
    assert len(asyncio.all_tasks()) > before
    await s.cancel(1)
    await asyncio.sleep(0.05)
    assert len(asyncio.all_tasks()) == before
    assert sink.of("turn.skipped")[0]["reason"] == "cancelled"
    assert not sink.of("turn.done")


async def test_new_turn_supersedes_unfinished_turn_and_close_releases_stt():
    stt = FakeSTT()
    s, sink = make(stt=stt, mt=FakeTranslator(ttft=0.5))
    await s.open()
    await s.turn_start(1, "en", "es")  # still capturing (no final commit): superseded
    s.audio(FRAME)
    await speak(s, turn_id=2)
    assert sink.of("turn.skipped")[0] == {"type": "turn.skipped", "turn_id": 1, "reason": "superseded"}
    await s.close()
    assert stt.closed


async def test_history_is_passed_as_context_for_next_turn():
    mt = FakeTranslator({"Good morning, doctor.": "Buenos días, doctor."})
    s, _sink = make(mt=mt)
    await speak(s, turn_id=1)
    await finish(s, 1)
    await speak(s, turn_id=2)
    await finish(s, 2)
    assert mt.calls[1][3].history == [("Good morning, doctor.", "Buenos días, doctor.")]


async def test_audio_after_final_commit_is_ignored():
    s, sink = make()
    await speak(s)
    s.audio(FRAME)  # late frame must not leak into the next turn or crash
    await finish(s)
    assert sink.of("turn.done")


# ---------------- speculative MT (M4) ----------------
class PartialFirstSTT(FakeSTT):
    """Like a streaming STT: the partial for a segment arrives BEFORE its commit;
    the final arrives `final_delay` after the commit. `late` = extra partial after commit."""

    def __init__(self, partial: str, final: str, final_delay: float = 0.15, late: str | None = None):
        super().__init__([final], final_delay=final_delay)
        self.partial, self.final, self.late = partial, final, late

    async def stream(self, audio, langs):
        from app.providers.base import Commit, TranscriptEvent
        sent_partial = False
        async for item in audio:
            if isinstance(item, bytes):
                if not sent_partial:
                    sent_partial = True
                    yield TranscriptEvent(seg=0, text=self.partial, final=False)
                continue
            assert isinstance(item, Commit)
            if self.late:
                await asyncio.sleep(0.02)
                yield TranscriptEvent(seg=0, text=self.late, final=False)
            await asyncio.sleep(self.final_delay)
            yield TranscriptEvent(seg=0, text=self.final, final=True, audio_s=0.1)
            return


def make_spec(stt, mt=None, tts=None):
    sink = Sink()
    s = CascadeSession(stt, mt or FakeTranslator({"Good morning, doctor.": "Buenos días, doctor."}),
                       tts or FakeTTS(first_byte=0.0), send_event=sink.event, send_audio=sink.send_audio,
                       voices={"es": "marin"}, speculative=True)
    return s, sink


async def _speak_until_audio_frames(s):
    await s.turn_start(1, "en", "es")
    for _ in range(3):
        s.audio(FRAME)
    await asyncio.sleep(0.02)  # let the partial arrive before the commit
    await s.commit(1, True)


async def test_speculation_hit_starts_mt_before_the_stt_final():
    mt = FakeTranslator({"Good morning, doctor": "Buenos días, doctor."})
    s, sink = make_spec(PartialFirstSTT("Good morning, doctor", "Good morning, doctor."), mt=mt)
    await _speak_until_audio_frames(s)
    await finish(s)
    done = sink.of("turn.done")[0]["marks"]
    assert done["mt_first_token"] < done["stt_final"]  # MT ran on the partial
    assert "spec_hit" in done
    assert len(mt.calls) == 1  # no second MT call for the matching final
    assert sink.of("translation.final")[0]["text"] == "Buenos días, doctor."
    assert sink.audio
    # transcript shows the STT final, not the partial
    assert sink.of("transcript.final")[0]["text"] == "Good morning, doctor."


async def test_speculation_miss_is_discarded_and_the_final_is_translated():
    mt = FakeTranslator({"Good morning": "Buenos días", "Good morning, doctor.": "Buenos días, doctor."})
    tts = FakeTTS(first_byte=0.0)
    s, sink = make_spec(PartialFirstSTT("Good morning", "Good morning, doctor."), mt=mt, tts=tts)
    await _speak_until_audio_frames(s)
    await finish(s)
    finals = sink.of("translation.final")
    assert [f["text"] for f in finals] == ["Buenos días, doctor."]  # speculative text never shown
    assert [c[0] for c in mt.calls] == ["Good morning", "Good morning, doctor."]
    assert "spec_hit" not in sink.of("turn.done")[0]["marks"]
    played = b"".join(p for _, p in sink.audio)
    assert played and sink.of("turn.done")


async def test_late_partial_restarts_the_speculation():
    mt = FakeTranslator({"Good": "Bueno", "Good morning, doctor": "Buenos días, doctor."})
    s, sink = make_spec(PartialFirstSTT("Good", "Good morning, doctor.", late="Good morning, doctor"), mt=mt)
    await _speak_until_audio_frames(s)
    await finish(s)
    assert [c[0] for c in mt.calls] == ["Good", "Good morning, doctor"]
    assert "spec_hit" in sink.of("turn.done")[0]["marks"]
    assert [f["text"] for f in sink.of("translation.final")] == ["Buenos días, doctor."]


async def test_speculation_error_does_not_fail_the_turn():
    class FailOnPartial(FakeTranslator):
        async def stream(self, text, src, tgt, ctx):
            if text == "Good morning":
                raise AuthError("boom", provider="fake", stage="mt")
            async for x in super().stream(text, src, tgt, ctx):
                yield x

    mt = FailOnPartial({"Good morning, doctor.": "Buenos días, doctor."})
    s, sink = make_spec(PartialFirstSTT("Good morning", "Good morning, doctor."), mt=mt)
    await _speak_until_audio_frames(s)
    await finish(s)
    assert not sink.of("error")
    assert sink.of("turn.done") and sink.audio


def test_norm_text_ignores_case_and_punctuation():
    from app.cascade.session import norm_text
    assert norm_text("¿Me duele  mucho la Cabeza?") == norm_text("me duele mucho la cabeza")
    assert norm_text("Good morning") != norm_text("Good morning, doctor")


async def test_pause_hint_speculates_before_any_commit():
    mt = FakeTranslator({"Good morning, doctor": "Buenos días, doctor."})
    s, sink = make_spec(PartialFirstSTT("Good morning, doctor", "Good morning, doctor."), mt=mt)
    await s.turn_start(1, "en", "es")
    s.audio(FRAME)
    await asyncio.sleep(0.02)
    s.pause_hint(1)  # browser: 150 ms of silence, no commit yet
    await asyncio.sleep(0.05)
    assert len(mt.calls) == 1  # MT already running on the partial
    await s.commit(1, True)  # same text at commit: no restart
    await finish(s)
    assert len(mt.calls) == 1
    assert "spec_hit" in sink.of("turn.done")[0]["marks"]


async def test_back_to_back_turn_queues_behind_a_committed_turn_instead_of_cancelling_it():
    # VAD mode: turn 1 ended (final commit) and is translating when turn 2 starts
    mt = FakeTranslator({"Good morning, doctor.": "Buenos días, doctor."})
    mt.ttft = 0.15
    s, sink = make(mt=mt)
    await speak(s, turn_id=1)
    await speak(s, turn_id=2)
    await finish(s, 1)
    await finish(s, 2)
    assert not [e for e in sink.of("turn.skipped") if e["reason"] == "superseded"]
    assert {e["turn_id"] for e in sink.of("turn.done")} == {1, 2}
    ids = [tid for tid, _ in sink.audio]
    assert ids == sorted(ids)  # all of turn 1's audio before any of turn 2's


async def test_uncommitted_turn_is_still_superseded():
    s, sink = make()
    await s.turn_start(1, "en", "es")
    s.audio(FRAME)
    await s.turn_start(2, "en", "es")
    await asyncio.sleep(0.05)
    assert sink.of("turn.skipped")[0]["reason"] == "superseded"


async def test_queued_turn_waits_for_the_previous_turns_stt_on_the_shared_socket():
    class OneAtATimeSTT(FakeSTT):
        active = 0
        overlap = False

        async def stream(self, audio, langs):
            OneAtATimeSTT.active += 1
            OneAtATimeSTT.overlap |= OneAtATimeSTT.active > 1
            try:
                async for ev in super().stream(audio, langs):
                    yield ev
            finally:
                OneAtATimeSTT.active -= 1

    s, sink = make(stt=OneAtATimeSTT(final_delay=0.1))
    await speak(s, turn_id=1)
    await speak(s, turn_id=2)
    await finish(s, 1)
    await finish(s, 2)
    assert not OneAtATimeSTT.overlap
    assert {e["turn_id"] for e in sink.of("turn.done")} == {1, 2}
