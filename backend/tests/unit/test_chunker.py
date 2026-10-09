from app.cascade.chunker import SentenceChunker, chunk_all


def toks(s: str) -> list[str]:
    """Simulate LLM streaming: word-ish tokens with leading spaces."""
    parts = s.split(" ")
    return [parts[0]] + [" " + p for p in parts[1:]]


def test_splits_on_sentence_terminators_with_min_length():
    out = chunk_all(toks("Buenos días, doctor. ¿Cómo está usted hoy? Bien."))
    assert out == ["Buenos días, doctor.", "¿Cómo está usted hoy?", "Bien."]


def test_short_sentence_is_held_until_min_length():
    assert chunk_all(toks("Sí. Claro que sí, señor.")) == ["Sí. Claro que sí, señor."]


def test_first_chunk_uses_lower_clause_threshold():
    text = "El paciente tiene dolor de cabeza, fiebre alta desde el martes, y náuseas por la mañana"
    out = chunk_all(toks(text))
    assert out[0] == "El paciente tiene dolor de cabeza,"  # >= 25 chars at first comma
    assert len(out) == 2  # second clause boundary is < 60 chars into the next chunk


def test_decimals_times_and_abbreviations_are_not_split():
    out = chunk_all(toks("La Dra. García le dio 2.5 mg a las 10:30 de la mañana. Vuelva el lunes por favor."))
    assert out == ["La Dra. García le dio 2.5 mg a las 10:30 de la mañana.", "Vuelva el lunes por favor."]


def test_spanish_multiword_abbreviations():
    out = chunk_all(toks("Use, p. ej. ibuprofeno, si vive en EE. UU. y tiene dolor."))
    assert out == ["Use, p. ej. ibuprofeno, si vive en EE. UU. y tiene dolor."]


def test_hard_cap_splits_at_whitespace():
    long = " ".join(["palabra"] * 40)  # 319 chars, no punctuation
    out = chunk_all(toks(long))
    assert all(len(c) <= 160 for c in out)
    assert " ".join(out) == long


def test_needs_lookahead_whitespace_then_emits_incrementally():
    c = SentenceChunker()
    assert c.feed("Tengo dolor de cabeza.") == []  # might still be "cabeza.5"? wait for next token
    assert c.feed(" Y") == ["Tengo dolor de cabeza."]
    assert c.flush() == ["Y"]
    assert c.flush() == []


def test_tokens_split_mid_word_and_punctuation():
    out = chunk_all(["Hel", "lo the", "re, my fri", "end. How", " are", " you", "?"])
    assert out == ["Hello there, my friend.", "How are you?"]
