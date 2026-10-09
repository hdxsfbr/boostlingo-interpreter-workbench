"""Fragment merging (M5): a short unpunctuated in-turn segment is translated
together with the next segment instead of alone ("¿Tienes? / ¿Alguna alergia?")."""
from app.cascade.session import CascadeSession, is_fragment
from app.providers.fakes import FakeSTT, FakeTranslator, FakeTTS

from .test_cascade_session import Sink, finish, speak


def make(stt, mt, merge=True, speculative=False):
    sink = Sink()
    s = CascadeSession(stt, mt, FakeTTS(first_byte=0.0), send_event=sink.event, send_audio=sink.send_audio,
                       voices={"es": "marin"}, merge_fragments=merge, speculative=speculative)
    return s, sink


def test_is_fragment_rule():
    assert is_fragment("Do you have")
    assert is_fragment("Me duele,")
    assert not is_fragment("Please have a seat.")
    assert not is_fragment("¿Tiene alguna alergia?")
    assert not is_fragment("one two three four five six seven")  # long enough to stand alone
    assert not is_fragment("")


async def test_fragment_is_merged_into_next_segment():
    mt = FakeTranslator({"Do you have any allergies?": "¿Tiene alguna alergia?"})
    s, sink = make(FakeSTT(["Do you have", "any allergies?"]), mt)
    await speak(s, commits=(False, True))
    await finish(s)
    assert [c[0] for c in mt.calls] == ["Do you have any allergies?"]
    assert [e["text"] for e in sink.of("translation.final")] == ["¿Tiene alguna alergia?"]
    assert [e["text"] for e in sink.of("transcript.final")] == ["Do you have", "any allergies?"]
    assert sink.audio


async def test_complete_sentences_are_not_merged():
    mt = FakeTranslator()
    s, _sink = make(FakeSTT(["Please have a seat.", "Thank you."]), mt)
    await speak(s, commits=(False, True))
    await finish(s)
    assert [c[0] for c in mt.calls] == ["Please have a seat.", "Thank you."]


async def test_turn_ending_on_a_fragment_still_translates_it():
    mt = FakeTranslator()
    s, sink = make(FakeSTT(["Do you have", " "]), mt)
    await speak(s, commits=(False, True))
    await finish(s)
    assert [c[0] for c in mt.calls] == ["Do you have"]
    assert sink.of("turn.done") and sink.audio


async def test_last_segment_is_never_held_even_if_short():
    mt = FakeTranslator()
    s, _sink = make(FakeSTT(["Do you have"]), mt)
    await speak(s, commits=(True,))
    await finish(s)
    assert [c[0] for c in mt.calls] == ["Do you have"]


async def test_merge_disabled_translates_fragments_separately():
    mt = FakeTranslator()
    s, _sink = make(FakeSTT(["Do you have", "any allergies?"]), mt, merge=False)
    await speak(s, commits=(False, True))
    await finish(s)
    assert [c[0] for c in mt.calls] == ["Do you have", "any allergies?"]


async def test_merge_with_speculation_translates_merged_text_once_audio_once():
    mt = FakeTranslator({"Do you have any allergies?": "¿Tiene alguna alergia?"})
    s, sink = make(FakeSTT(["Do you have", "any allergies?"]), mt, speculative=True)
    await speak(s, commits=(False, True))
    await finish(s)
    finals = [e["text"] for e in sink.of("translation.final")]
    assert finals == ["¿Tiene alguna alergia?"]
    # every MT call that was used for audio carried the merged text
    assert "Do you have any allergies?" in [c[0] for c in mt.calls]
    assert len(sink.audio) == 2 * 1  # one TTS chunk -> two frames, no duplicate speech
