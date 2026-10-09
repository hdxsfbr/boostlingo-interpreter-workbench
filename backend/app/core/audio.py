"""PCM16 mono 24 kHz helpers."""
from __future__ import annotations

import array

SAMPLE_RATE = 24000
BYTES_PER_MS = SAMPLE_RATE * 2 // 1000  # 48


def first_loud_sample(pcm: bytes, threshold: float = 0.003) -> int | None:
    """Index (in samples) of the first sample with |x| >= threshold, else None."""
    a = array.array("h", pcm[: len(pcm) // 2 * 2])
    lim = int(threshold * 32768)
    for i, x in enumerate(a):
        if x >= lim or -x >= lim:
            return i
    return None


class LeadingSilenceTrimmer:
    """Drops near-silent samples at the start of a stream (keeping `pad_ms`),
    then passes everything through. Also re-aligns odd byte splits so every
    yielded chunk holds whole 16-bit samples."""

    def __init__(self, threshold: float = 0.003, pad_ms: int = 20, max_trim_ms: int = 600) -> None:
        self.threshold = threshold
        self.pad = pad_ms * BYTES_PER_MS
        self.max_trim = max_trim_ms * BYTES_PER_MS
        self.trimming = True
        self.held = b""
        self.carry = b""
        self.trimmed_bytes = 0

    def feed(self, data: bytes) -> bytes:
        data = self.carry + data
        cut = len(data) // 2 * 2
        data, self.carry = data[:cut], data[cut:]
        if not self.trimming:
            return data
        self.held += data
        idx = first_loud_sample(self.held, self.threshold)
        if idx is None:
            if len(self.held) < self.max_trim:
                return b""
            idx = len(self.held) // 2
        start = max(0, idx * 2 - self.pad)
        self.trimmed_bytes = start
        out, self.held, self.trimming = self.held[start:], b"", False
        return out

    def flush(self) -> bytes:
        out = self.held if self.trimming else b""
        self.held, self.trimming = b"", False
        return out
