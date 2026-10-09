"""CascadeSession: the streaming STT -> MT -> chunker -> TTS orchestrator (FR-3).

Depends only on the provider Protocols (CQ-2). Per turn:

    audio frames + commits --> STT --(segment finals)--> per-segment task:
        MT tokens --> SentenceChunker --> TTS --> segment audio queue
    sender: after the final commit (playback policy after_speech_end), drains
    segment audio queues strictly in segment order --> browser

Segments run concurrently (segment k+1 translates while k speaks) but audio
leaves in order. Stages are joined by bounded asyncio queues (backpressure,
FR-3.4) inside one TaskGroup, so cancelling the turn (barge-in, mode switch,
disconnect, watchdog) tears everything down.

Latency marks are server-monotonic durations from the FINAL commit; marks
recorded before it (pipelined early segments) are emitted, possibly negative,
once the final commit arrives.

Speculative MT (M4, optional): STT partials stream while the user speaks, so
when a segment is committed its partial transcript is usually already
complete, ~0.4-0.6 s before the STT `completed` final. At each commit we start
MT -> TTS on that partial (restarting if a later partial for the segment
changes it). When the final arrives: if it matches the speculated text
(case/punctuation-insensitive) the speculative run is adopted as the segment;
otherwise it is cancelled and the segment runs normally on the final text.
Speculative output (audio, translation events, latency marks) is held until
adopted, so a miss is invisible to the user and costs only the wasted calls.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.cascade.chunker import SentenceChunker
from app.core.errors import EmptyResult, ProviderError, ProviderTimeout
from app.core.events import ErrorEvent, LatencyMark, TranslationEvent, TurnDone, TurnSkipped, TurnStarted
from app.core.events import TranscriptEvent as TranscriptOut
from app.core.retry import stream_with_retry
from app.providers.base import Commit, STTProvider, Translator, TTSProvider, TurnContext, Usage

log = logging.getLogger(__name__)

SendEvent = Callable[[Any], Awaitable[None]]
SendAudio = Callable[[int, bytes], Awaitable[None]]
_EMPTY = re.compile(r"^[\s\W_]*$", re.UNICODE)
_NONWORD = re.compile(r"[\W_]+", re.UNICODE)


def norm_text(text: str) -> str:
    """Case/punctuation/whitespace-insensitive form used to accept a speculation."""
    return " ".join(_NONWORD.sub(" ", (text or "").lower()).split())


def is_empty_text(text: str) -> bool:
    """Empty or punctuation-only (CQ-4 empty result)."""
    return bool(_EMPTY.match(text or ""))


def _first_provider_error(eg: BaseExceptionGroup) -> ProviderError | None:
    for exc in eg.exceptions:
        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, BaseExceptionGroup) and (inner := _first_provider_error(exc)):
            return inner
    return None


@dataclass
class Timeouts:
    stt_final: float = 3.0
    mt_first_token: float = 3.0
    tts_first_byte: float = 3.0
    turn: float = 20.0

    @classmethod
    def from_config(cls, cfg: dict) -> Timeouts:
        return cls(**{k: float(v) for k, v in cfg.items() if k in cls.__dataclass_fields__})


async def first_within(it: AsyncIterator, seconds: float, stage: str, provider: str = "") -> AsyncIterator:
    """Re-yield `it`, raising ProviderTimeout if the FIRST item takes too long."""
    ait = aiter(it)
    try:
        try:
            first = await asyncio.wait_for(anext(ait), seconds)
        except StopAsyncIteration:
            return
        except TimeoutError:
            raise ProviderTimeout(f"{stage}: no output within {seconds:.1f}s", stage=stage,
                                  provider=provider) from None
        yield first
        async for x in ait:
            yield x
    finally:
        aclose = getattr(ait, "aclose", None)
        if aclose:
            await aclose()


class ReplayableChunks:
    """Chunk source for TTS that can be re-iterated (for a retry before first
    byte) by replaying the chunks already consumed, then continuing."""

    def __init__(self, q: asyncio.Queue, on_chunk: Callable[[str], None]) -> None:
        self.q = q
        self.seen: list[str] = []
        self.done = False
        self.on_chunk = on_chunk

    def __call__(self) -> AsyncIterator[str]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[str]:
        for c in list(self.seen):
            yield c
        while not self.done:
            c = await self.q.get()
            if c is None:
                self.done = True
                return
            self.seen.append(c)
            self.on_chunk(c)
            yield c


@dataclass
class Spec:
    """A speculative segment run on a partial transcript (held until adopted)."""
    seg: int
    text: str
    queue: asyncio.Queue
    task: asyncio.Task | None = None
    confirmed: bool = False
    marks: dict[str, float] = field(default_factory=dict)
    out_text: str = ""
    mt_done: bool = False


@dataclass
class Turn:
    id: int
    src: str
    tgt: str
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1500))  # ~30 s of 20 ms frames
    final_commit: asyncio.Event = field(default_factory=asyncio.Event)
    t_final_commit: float | None = None
    marks: dict[str, float] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    task: asyncio.Task | None = None
    fail: ProviderError | None = None
    watchdogs: list[asyncio.Task] = field(default_factory=list)
    after: asyncio.Task | None = None  # previous turn still translating: play after it (VAD back-to-back turns)
    source_text: list[str] = field(default_factory=list)
    target_text: dict[int, str] = field(default_factory=dict)
    audio_bytes: int = 0
    # speculative MT bookkeeping
    tg: asyncio.TaskGroup | None = None
    n_commits: int = 0
    partials: dict[int, str] = field(default_factory=dict)
    finalized: set[int] = field(default_factory=set)
    specs: dict[int, Spec] = field(default_factory=dict)
    spec_stats: dict[str, int] = field(default_factory=lambda: {"started": 0, "hit": 0, "miss": 0})


class CascadeSession:
    def __init__(self, stt: STTProvider, mt: Translator, tts: TTSProvider, *, send_event: SendEvent,
                 send_audio: SendAudio, voices: dict[str, str] | None = None, langs: list[str] | None = None,
                 timeouts: Timeouts | None = None, glossary: dict[str, str] | None = None,
                 history_turns: int = 2, clock: Callable[[], float] = time.monotonic,
                 speculative: bool = False, chunker: dict[str, Any] | None = None) -> None:
        self.stt, self.mt, self.tts = stt, mt, tts
        self.send_event, self.send_audio = send_event, send_audio
        self.voices = voices or {}
        self.langs = langs or ["en", "es"]
        self.timeouts = timeouts or Timeouts()
        self.glossary = glossary or {}
        self.history: list[tuple[str, str]] = []
        self.history_turns = history_turns
        self.clock = clock
        self.speculative = speculative
        self.chunker_kwargs = dict(chunker or {})
        self.turn: Turn | None = None
        self._turns: dict[int, Turn] = {}

    # ---------------- lifecycle ----------------
    async def open(self) -> None:
        await self.stt.open()

    async def close(self) -> None:
        for t in list(self._turns.values()):
            await self._cancel_turn(t, reason=None)
        await self.stt.aclose()

    # ---------------- inputs from the gateway ----------------
    async def turn_start(self, turn_id: int, src: str, tgt: str) -> None:
        prev = self.turn
        after = None
        if prev is not None and prev.task and not prev.task.done():
            if prev.final_commit.is_set():
                # The previous turn is complete on the input side and still being
                # translated (e.g. VAD ended it and the speaker went on). Keep it and
                # queue this turn's audio behind it; barge-in sends an explicit cancel.
                after = prev.task
            else:
                await self._cancel_turn(prev, reason="superseded")
        t = Turn(id=turn_id, src=src, tgt=tgt, after=after)
        self.turn = t
        self._turns[turn_id] = t
        await self.send_event(TurnStarted(turn_id=turn_id, src=src, tgt=tgt))
        t.task = asyncio.create_task(self._run_turn(t), name=f"turn-{turn_id}")

    def audio(self, pcm: bytes) -> None:
        t = self.turn
        if t is None or t.final_commit.is_set():
            return
        try:
            t.queue.put_nowait(pcm)
        except asyncio.QueueFull:
            log.warning("turn %s audio queue full; dropping frame", t.id)

    async def commit(self, turn_id: int, final: bool) -> None:
        t = self._turns.get(turn_id)
        if t is None or t.final_commit.is_set():
            return
        await t.queue.put(Commit(final=final))
        seg = t.n_commits
        t.n_commits += 1
        if seg in t.partials:
            self._speculate(t, seg, t.partials[seg])
        if final:
            t.t_final_commit = self.clock()
            t.final_commit.set()
            for name, at in list(t.marks.items()):
                await self._emit_mark(t, name, at)
            t.watchdogs.append(asyncio.create_task(self._watchdog(t, "stt", self.timeouts.stt_final,
                                                                  until=lambda: "stt_final" in t.marks)))
            t.watchdogs.append(asyncio.create_task(self._watchdog(t, "turn", self.timeouts.turn)))
            self._mark(t, "commit_received")

    def pause_hint(self, turn_id: int) -> None:
        """Short in-turn silence seen by the browser (before any commit): speculate
        on the current partial of the not-yet-committed segment."""
        t = self._turns.get(turn_id)
        if t is None or t.final_commit.is_set():
            return
        seg = t.n_commits
        if seg in t.partials:
            self._speculate(t, seg, t.partials[seg])

    async def cancel(self, turn_id: int) -> None:
        t = self._turns.get(turn_id)
        if t is not None:
            await self._cancel_turn(t, reason="cancelled")

    # ---------------- internals ----------------
    async def _cancel_turn(self, t: Turn, reason: str | None) -> None:
        for w in t.watchdogs:
            w.cancel()
        if t.task and not t.task.done():
            t.task.cancel()
            try:
                await t.task
            except asyncio.CancelledError:
                pass  # expected: we just cancelled it
            except Exception:  # the turn task already reported its error to the client
                log.debug("cancelled turn %s ended with an error", t.id, exc_info=True)
            if reason:
                await self.send_event(TurnSkipped(turn_id=t.id, reason=reason))
        self._turns.pop(t.id, None)
        if self.turn is t:
            self.turn = None

    async def _watchdog(self, t: Turn, stage: str, seconds: float, until: Callable[[], bool] | None = None) -> None:
        await asyncio.sleep(seconds)
        if t.task and not t.task.done() and not (until and until()):
            t.fail = ProviderTimeout(f"{stage} timed out after {seconds:.1f}s", stage=stage)
            t.task.cancel()

    def _mark(self, t: Turn, name: str, once: bool = True) -> None:
        if once and name in t.marks:
            return
        t.marks[name] = self.clock()
        if t.t_final_commit is not None and not name.startswith("tail_"):
            asyncio.get_running_loop().create_task(self._emit_mark(t, name, t.marks[name]))

    async def _emit_mark(self, t: Turn, name: str, at: float) -> None:
        if t.t_final_commit is None or name == "commit_received":
            return
        await self.send_event(LatencyMark(turn_id=t.id, mark=name, ms=round((at - t.t_final_commit) * 1000, 1)))

    def _rel_marks(self, t: Turn) -> dict[str, float]:
        base = t.t_final_commit or 0.0
        return {k: round((v - base) * 1000, 1) for k, v in t.marks.items() if k != "commit_received"}

    async def _audio_iter(self, t: Turn) -> AsyncIterator[bytes | Commit]:
        while True:
            item = await t.queue.get()
            yield item
            if isinstance(item, Commit) and item.final:
                return

    async def _run_turn(self, t: Turn) -> None:
        segq_list: asyncio.Queue = asyncio.Queue()
        n_text_segments = 0
        try:
            async with asyncio.TaskGroup() as tg:
                t.tg = tg
                tg.create_task(self._sender(t, segq_list))
                async for ev in self.stt.stream(self._audio_iter(t), self.langs):
                    if not ev.final:
                        await self.send_event(TranscriptOut(type="transcript.partial", turn_id=t.id, seg=ev.seg,
                                                            text=ev.text))
                        if ev.seg not in t.finalized:
                            t.partials[ev.seg] = ev.text
                            if ev.seg < t.n_commits:  # already committed: (re)speculate on the newer text
                                self._speculate(t, ev.seg, ev.text)
                        continue
                    t.finalized.add(ev.seg)
                    spec = t.specs.pop(ev.seg, None)
                    t.usage.stt_audio_s += ev.audio_s
                    await self.send_event(TranscriptOut(type="transcript.final", turn_id=t.id, seg=ev.seg,
                                                        text=ev.text))
                    if t.final_commit.is_set():
                        self._mark(t, "stt_final", once=False)  # last final after the commit
                    hit = spec is not None and not is_empty_text(ev.text) and norm_text(spec.text) == norm_text(ev.text)
                    if spec is not None and not hit:
                        t.spec_stats["miss"] += 1
                        if spec.task:
                            spec.task.cancel()
                    if is_empty_text(ev.text):
                        continue
                    n_text_segments += 1
                    t.source_text.append(ev.text.strip())
                    if hit:
                        t.spec_stats["hit"] += 1
                        await self._adopt(t, spec)
                        await segq_list.put(spec.queue)
                        continue
                    q: asyncio.Queue = asyncio.Queue(maxsize=256)
                    await segq_list.put(q)
                    tg.create_task(self._segment(t, ev.seg, ev.text.strip(), q))
                self._mark(t, "stt_final")  # ensure present even if every final came early
                await segq_list.put(None)
        except asyncio.CancelledError:
            if t.fail is None:
                raise
            asyncio.current_task().uncancel()
            await self._fail(t, t.fail)
            return
        except BaseExceptionGroup as eg:
            perr = _first_provider_error(eg)
            if perr is None:
                raise
            await self._fail(t, perr)
            return
        finally:
            t.tg = None
            for w in t.watchdogs:
                w.cancel()
            self._turns.pop(t.id, None)
            if self.turn is t:
                self.turn = None

        if n_text_segments == 0:
            await self.send_event(TurnSkipped(turn_id=t.id, reason="empty_transcript"))
            return
        if t.audio_bytes == 0:
            await self.send_event(TurnSkipped(turn_id=t.id, reason="empty_translation"))
            return
        translation = " ".join(t.target_text[k] for k in sorted(t.target_text))
        self.history = (self.history + [(" ".join(t.source_text), translation)])[-self.history_turns:]
        marks = self._rel_marks(t)
        if t.spec_stats["started"]:
            log.info("turn %s speculative MT: %s", t.id, t.spec_stats)
        if "tail_tts_first_byte" in marks:
            await self.send_event(LatencyMark(turn_id=t.id, mark="tail_tts_first_byte",
                                              ms=marks["tail_tts_first_byte"]))
        await self.send_event(TurnDone(turn_id=t.id, marks=marks, usage=t.usage.as_dict()))

    async def _fail(self, t: Turn, exc: ProviderError) -> None:
        stage = exc.stage or "pipeline"
        log.warning("turn %s failed at %s: %s", t.id, stage, exc.code)
        await self.send_event(ErrorEvent(code=exc.code, stage=stage, retryable=False, turn_id=t.id,
                                         message=f"{stage} failed: {exc}"))

    # ---------------- speculative MT ----------------
    def _speculate(self, t: Turn, seg: int, text: str) -> None:
        """Start (or restart) a held MT -> TTS run for a committed segment's partial."""
        if not self.speculative or t.tg is None or seg in t.finalized or is_empty_text(text):
            return
        old = t.specs.get(seg)
        if old is not None:
            if norm_text(old.text) == norm_text(text):
                return
            if old.task:
                old.task.cancel()
        sp = Spec(seg=seg, text=text.strip(), queue=asyncio.Queue(maxsize=256))
        t.specs[seg] = sp
        t.spec_stats["started"] += 1
        self._mark(t, "spec_start", once=False)
        try:
            sp.task = t.tg.create_task(self._spec_run(t, sp))
        except RuntimeError:  # task group is shutting down
            t.specs.pop(seg, None)

    async def _spec_run(self, t: Turn, sp: Spec) -> None:
        """A provider error in a not-yet-adopted speculation must not fail the turn:
        drop it and let the final run the normal path."""
        try:
            await self._segment(t, sp.seg, sp.text, sp.queue, spec=sp)
        except (ProviderError, BaseExceptionGroup) as e:
            if sp.confirmed:
                raise
            log.info("turn %s seg %s: speculative run dropped (%s)", t.id, sp.seg, type(e).__name__)
            if t.specs.get(sp.seg) is sp:
                t.specs.pop(sp.seg)

    async def _adopt(self, t: Turn, sp: Spec) -> None:
        """The final matched: publish the held marks and translation, then go live."""
        sp.confirmed = True
        self._mark(t, "spec_hit", once=False)
        for name, at in sorted(sp.marks.items(), key=lambda kv: kv[1]):
            if name.startswith("tail_") or name not in t.marks:
                t.marks[name] = at
                if t.t_final_commit is not None and not name.startswith("tail_"):
                    await self._emit_mark(t, name, at)
        if sp.out_text:
            await self.send_event(TranslationEvent(type="translation.partial", turn_id=t.id, seg=sp.seg,
                                                   text=sp.out_text.strip()))
        if sp.mt_done:
            await self.send_event(TranslationEvent(type="translation.final", turn_id=t.id, seg=sp.seg,
                                                   text=sp.out_text.strip()))

    def _smark(self, t: Turn, sp: Spec | None, name: str, once: bool = True) -> None:
        if sp is None or sp.confirmed:
            self._mark(t, name, once)
        elif not (once and name in sp.marks):
            sp.marks[name] = self.clock()

    async def _notice_retry(self, t: Turn, stage: str, exc: ProviderError, attempt: int, delay: float) -> None:
        await self.send_event(ErrorEvent(code=exc.code, stage=stage, retryable=True, turn_id=t.id,
                                         message=f"{stage} {exc.code}; retry {attempt} in {delay * 1000:.0f} ms"))

    async def _sender(self, t: Turn, segq_list: asyncio.Queue) -> None:
        await t.final_commit.wait()  # playback policy: after_speech_end (D8)
        if t.after is not None:  # keep turns' audio in order (never interleave two turns)
            await asyncio.wait({t.after})
        while (segq := await segq_list.get()) is not None:
            while (pcm := await segq.get()) is not None:
                if t.audio_bytes == 0:
                    self._mark(t, "audio_first_sent")
                t.audio_bytes += len(pcm)
                await self.send_audio(t.id, pcm)

    async def _segment(self, t: Turn, seg: int, text: str, outq: asyncio.Queue, spec: Spec | None = None) -> None:
        chunkq: asyncio.Queue = asyncio.Queue(maxsize=32)
        ctx = TurnContext(history=list(self.history), glossary=dict(self.glossary))
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._mt_stage(t, seg, text, ctx, chunkq, spec))
                tg.create_task(self._tts_stage(t, seg, chunkq, outq, spec))
        finally:
            try:
                outq.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def _mt_stage(self, t: Turn, seg: int, text: str, ctx: TurnContext, chunkq: asyncio.Queue,
                        spec: Spec | None = None) -> None:
        chunker = SentenceChunker(**self.chunker_kwargs)
        out = ""

        async def retry_notice(exc, attempt, delay):
            await self._notice_retry(t, "mt", exc, attempt, delay)

        stream = stream_with_retry(lambda: self.mt.stream(text, t.src, t.tgt, ctx), on_retry=retry_notice)
        try:
            async for tok in first_within(stream, self.timeouts.mt_first_token, "mt", self.mt.name):
                if not out:
                    self._smark(t, spec, "mt_first_token")
                out += tok
                if spec is not None:
                    spec.out_text = out
                if spec is None or spec.confirmed:
                    await self.send_event(TranslationEvent(type="translation.partial", turn_id=t.id, seg=seg,
                                                           text=out.strip()))
                for c in chunker.feed(tok):
                    self._smark(t, spec, "mt_first_chunk")
                    await chunkq.put(c)
            for c in chunker.flush():
                self._smark(t, spec, "mt_first_chunk")
                await chunkq.put(c)
        except ProviderError as e:
            e.stage = e.stage or "mt"
            raise
        finally:
            await chunkq.put(None)
        u = getattr(self.mt, "last_usage", None)
        if u:
            t.usage.mt_input_tokens += u.mt_input_tokens
            t.usage.mt_output_tokens += u.mt_output_tokens
        t.target_text[seg] = out.strip()
        if spec is not None:
            spec.mt_done = True
        if spec is None or spec.confirmed:
            await self.send_event(TranslationEvent(type="translation.final", turn_id=t.id, seg=seg, text=out.strip()))
        if is_empty_text(out):
            log.info("turn %s seg %s: empty translation", t.id, seg)

    async def _tts_stage(self, t: Turn, seg: int, chunkq: asyncio.Queue, outq: asyncio.Queue,
                         spec: Spec | None = None) -> None:
        first = await chunkq.get()
        if first is None:
            return  # empty translation: nothing to speak

        def on_chunk(c: str) -> None:
            t.usage.tts_chars += len(c)

        src = ReplayableChunks(chunkq, on_chunk)
        src.seen.append(first)
        on_chunk(first)
        self._smark(t, spec, "tts_request")
        voice = self.voices.get(t.tgt, "")

        async def retry_notice(exc, attempt, delay):
            await self._notice_retry(t, "tts", exc, attempt, delay)

        stream = stream_with_retry(lambda: self.tts.stream(src(), t.tgt, voice), on_retry=retry_notice)
        got = False
        try:
            async for pcm in first_within(stream, self.timeouts.tts_first_byte, "tts", self.tts.name):
                if not pcm:
                    continue
                if not got:
                    got = True
                    self._smark(t, spec, "tts_first_byte")
                    self._smark(t, spec, "tail_tts_first_byte", once=False)
                await outq.put(pcm)
        except ProviderError as e:
            e.stage = e.stage or "tts"
            raise
        if not got:
            raise EmptyResult("TTS returned no audio", stage="tts", provider=self.tts.name)
