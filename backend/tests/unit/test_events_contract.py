"""The shared fixtures must round-trip through the pydantic contract."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.events import client_message_adapter, pack_audio, server_event_adapter, unpack_audio

FIX = Path(__file__).resolve().parents[3] / "contract" / "fixtures"


@pytest.mark.parametrize("raw", json.loads((FIX / "server_events.json").read_text()))
def test_server_fixtures_roundtrip(raw):
    ev = server_event_adapter.validate_python(raw)
    assert json.loads(ev.model_dump_json()) == raw


@pytest.mark.parametrize("raw", json.loads((FIX / "client_messages.json").read_text()))
def test_client_fixtures_roundtrip(raw):
    msg = client_message_adapter.validate_python(raw)
    assert json.loads(msg.model_dump_json()) == raw


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        server_event_adapter.validate_python({"type": "turn.started", "turn_id": 1, "src": "en",
                                              "tgt": "es", "extra": 1})


def test_audio_frame_header_roundtrip():
    pcm = b"\x01\x00\xff\x7f" * 10
    assert unpack_audio(pack_audio(42, pcm)) == (42, pcm)
