"""Orchestrator tests with scripted fake providers (CQ-3.1 / CQ-3.3)."""
import asyncio

import pytest

from app.cascade.session import CascadeSession, Timeouts, is_empty_text
from app.core.errors import AuthError, ProviderTimeout, RateLimited
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
    await speak(s, turn_id=1)
    await speak(s, turn_id=2)
    assert sink.of("turn.skipped")[0] == {"type": "turn.skipped", "turn_id": 1, "reason": "superseded"}
    await s.close()
    assert stt.closed


async def test_history_is_passed_as_context_for_next_turn():
    mt = FakeTranslator({"Good morning, doctor.": "Buenos días, doctor."})
    s, sink = make(mt=mt)
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
