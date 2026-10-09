"""Sentence/clause chunker between the streaming translator and TTS (DESIGN §3).

Pure and incremental: feed() tokens as they stream, get back chunks ready for
TTS; flush() at end of stream. Rules:
- emit at a sentence terminator (. ? ! …) followed by whitespace, if >= 12 chars;
- emit at a clause boundary (, ; :) followed by whitespace once >= 60 chars are
  buffered (25 for the FIRST chunk, to get first audio out sooner);
- hard cap: 160 chars, split at the last whitespace;
- optional `first_word_min` (M4 tuning, off by default): if the FIRST chunk has
  no boundary yet once this many chars are buffered, cut at the last word
  boundary, trading a prosody seam for earlier first audio;
- never split inside decimals/times ("3.5", "10:30": no whitespace follows)
  or after known abbreviations ("Dr.", "Sra.", "p. ej.", "EE. UU.").
"""
from __future__ import annotations

import re

SENTENCE_END = ".?!…"
CLAUSE_END = ",;:"
ABBREVIATIONS = {
    "dr", "dra", "sr", "sra", "srta", "mr", "mrs", "ms", "st", "jr", "vs", "etc", "e.g", "i.e", "no",
    "p", "ej", "ee", "uu", "ud", "uds", "lic", "ing", "prof", "approx", "aprox", "núm", "tel", "a.m", "p.m",
}
_WORD_BEFORE = re.compile(r"([\wÁÉÍÓÚÑáéíóúñü.]+)\.$")


class SentenceChunker:
    def __init__(self, min_sentence: int = 12, clause_min: int = 60, first_clause_min: int = 25,
                 hard_cap: int = 160, first_word_min: int | None = None) -> None:
        self.min_sentence = min_sentence
        self.clause_min = clause_min
        self.first_clause_min = first_clause_min
        self.hard_cap = hard_cap
        self.first_word_min = first_word_min
        self.buf = ""
        self.emitted = 0

    def _is_abbreviation(self, upto: str) -> bool:
        m = _WORD_BEFORE.search(upto)
        if not m:
            return False
        word = m.group(1).lower().rstrip(".")
        last = word.split(".")[-1]
        return word in ABBREVIATIONS or last in ABBREVIATIONS or (len(last) == 1 and last.isalpha())

    def _find_cut(self) -> int | None:
        """Index just after the boundary char, or None."""
        b = self.buf
        clause_min = self.first_clause_min if self.emitted == 0 else self.clause_min
        for i, ch in enumerate(b):
            nxt = b[i + 1] if i + 1 < len(b) else None
            if nxt is None or not nxt.isspace():
                continue  # need lookahead whitespace (protects 3.5, 10:30, "...")
            seg = b[: i + 1].strip()
            if ch in SENTENCE_END and len(seg) >= self.min_sentence:
                if ch == "." and self._is_abbreviation(b[: i + 1]):
                    continue
                return i + 1
            if ch in CLAUSE_END and len(seg) >= clause_min:
                return i + 1
        if self.emitted == 0 and self.first_word_min and len(b) >= self.first_word_min:
            sp = b.rfind(" ", 0, len(b))
            if sp > 0 and len(b[:sp].strip()) >= self.first_word_min // 2:
                return sp
        if len(b) >= self.hard_cap:
            sp = b.rfind(" ", 0, self.hard_cap)
            return sp if sp > 0 else self.hard_cap
        return None

    def feed(self, token: str) -> list[str]:
        self.buf += token
        out = []
        while (cut := self._find_cut()) is not None:
            chunk, self.buf = self.buf[:cut].strip(), self.buf[cut:].lstrip()
            if chunk:
                out.append(chunk)
                self.emitted += 1
        return out

    def flush(self) -> list[str]:
        chunk, self.buf = self.buf.strip(), ""
        if chunk:
            self.emitted += 1
            return [chunk]
        return []


def chunk_all(tokens: list[str], **kw) -> list[str]:
    c = SentenceChunker(**kw)
    out = [x for t in tokens for x in c.feed(t)]
    return out + c.flush()
