import json

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def test_turn_records_append_to_session_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    c = TestClient(create_app())
    for i in (1, 2):
        r = c.post("/api/turns", json={"session_id": "s-1", "record": {"turn_id": i, "latency_ms": 1234.5}})
        assert r.status_code == 204
    lines = (tmp_path / "sessions" / "s-1.jsonl").read_text().splitlines()
    assert [json.loads(x)["record"]["turn_id"] for x in lines] == [1, 2]
    assert c.post("/api/turns", json={"session_id": "../etc", "record": {}}).status_code == 400
    get_settings.cache_clear()
