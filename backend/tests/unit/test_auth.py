"""A15 password gate: every surface is protected when APP_USERNAME/APP_PASSWORD are set."""
import base64
import logging

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from app.core.auth import COOKIE, AuthGate, credentials_from_env
from app.core.config import get_settings

USER, PW = "andre", "correct horse battery staple"
GOOD = "Basic " + base64.b64encode(f"{USER}:{PW}".encode()).decode()
BAD = "Basic " + base64.b64encode(f"{USER}:wrong".encode()).decode()

HTTP = [
    ("GET", "/"), ("GET", "/index.html"), ("GET", "/assets/app.js"), ("GET", "/docs"), ("GET", "/openapi.json"),
    ("GET", "/api/health"), ("GET", "/api/languages"),
    ("POST", "/api/realtime/session"),  # ephemeral Realtime token
    ("POST", "/api/turns"),
    ("GET", "/api/recordings/config"), ("POST", "/api/recordings/s1/turns/1/source"), ("DELETE", "/api/recordings/s1"),
    ("GET", "/api/review/sets"), ("GET", "/api/review/sets/blind-m5"), ("GET", "/api/review/sets/blind-m5/items/x/audio"),
    ("PUT", "/api/review/sets/blind-m5/items/x/rating"), ("GET", "/api/review/sets/blind-m5/results.csv"),
    ("GET", "/api/experiments"), ("GET", "/api/experiments/setups"), ("POST", "/api/experiments/estimate"),
    ("POST", "/api/experiments"), ("GET", "/api/experiments/m5-baseline/events"),  # SSE
    ("GET", "/api/experiments/m5-baseline/export.csv"), ("POST", "/api/experiments/x/cancel"),
]
WS = ["/ws/cascade", "/ws/realtime"]


@pytest.fixture
def gated(tmp_path, monkeypatch):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>spa</html>")
    (static / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setenv("STATIC_DIR", str(static))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("APP_USERNAME", USER)
    monkeypatch.setenv("APP_PASSWORD", PW)
    get_settings.cache_clear()
    from app.main import create_app
    yield TestClient(create_app(), base_url="https://wb.example")
    get_settings.cache_clear()


@pytest.mark.parametrize(("method", "path"), HTTP)
def test_every_http_surface_needs_auth(gated, method, path):
    for headers in ({}, {"Authorization": BAD}, {"Authorization": "Basic !!!"}, {"Cookie": f"{COOKIE}=1.forged"}):
        r = gated.request(method, path, headers=headers)
        assert r.status_code == 401, (path, headers, r.status_code)
        assert r.headers["www-authenticate"].startswith("Basic realm=")
        assert "set-cookie" not in r.headers


@pytest.mark.parametrize("path", WS)
def test_every_websocket_needs_auth(gated, path):
    with pytest.raises(WebSocketDenialResponse) as e, gated.websocket_connect(path):
        pass
    assert e.value.status_code == 401


def test_healthz_stays_open_and_minimal(gated):
    r = gated.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_basic_sets_signed_cookie_which_then_covers_http_sse_and_ws(gated):
    r = gated.get("/", headers={"Authorization": GOOD})
    assert r.status_code == 200 and "spa" in r.text
    sc = r.headers["set-cookie"]
    assert sc.startswith(f"{COOKIE}=") and "HttpOnly" in sc and "SameSite=Strict" in sc and "Secure" in sc
    assert PW not in sc
    token = sc.split(";")[0].split("=", 1)[1]
    gated.cookies.clear()
    h = {"Cookie": f"{COOKIE}={token}"}
    assert gated.get("/api/languages", headers=h).status_code == 200
    assert gated.get("/api/experiments", headers=h).status_code == 200
    # WS with the cookie gets through the gate (the endpoint then speaks its own protocol)
    with gated.websocket_connect("/ws/realtime", headers={**h, "Origin": "http://testserver"}) as ws:  # TestClient WS Host is testserver
        ws.send_text("not json")
        assert "bad_message" in ws.receive_text()
    # a cross-site page cannot ride the cookie (CSWSH guard)
    with pytest.raises(WebSocketDenialResponse), gated.websocket_connect(
            "/ws/realtime", headers={**h, "Origin": "https://evil.example"}):
        pass


def test_cookie_expires_and_is_bound_to_the_password():
    t = [1000.0]
    gate = AuthGate(None, USER, PW, now=lambda: t[0])
    tok = gate.make_cookie()
    assert gate.cookie_ok(tok)
    t[0] += 13 * 3600
    assert not gate.cookie_ok(tok)
    assert not AuthGate(None, USER, "rotated", now=lambda: 1000.0).cookie_ok(AuthGate(None, USER, PW, now=lambda: 1000.0).make_cookie())
    assert not gate.cookie_ok("9999999999." + "0" * 64)
    assert gate.basic_ok(GOOD) and not gate.basic_ok(BAD) and not gate.basic_ok(None)
    assert not gate.basic_ok("Basic " + base64.b64encode(USER.encode()).decode())  # no colon


def test_unset_means_open_and_hosted_without_password_warns(caplog):
    assert credentials_from_env({}) is None
    assert credentials_from_env({"APP_USERNAME": "andre"}) is None  # both are required
    assert credentials_from_env({"APP_USERNAME": "a", "APP_PASSWORD": "b"}) == ("a", "b")
    with caplog.at_level(logging.WARNING, logger="app.auth"):
        assert credentials_from_env({"PORT": "8080", "RAILWAY_ENVIRONMENT": "production"}) is None
    assert "PASSWORD GATE OFF" in caplog.text


def test_ungated_app_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    from app.main import create_app
    c = TestClient(create_app())
    assert c.get("/api/languages").status_code == 200
    with c.websocket_connect("/ws/realtime") as ws:
        ws.send_text("x")
        assert "bad_message" in ws.receive_text()
    get_settings.cache_clear()


def test_experiment_runner_harness_authenticates_from_inherited_env(monkeypatch, tmp_path):
    from eval import auth
    monkeypatch.setenv("APP_USERNAME", USER)
    monkeypatch.setenv("APP_PASSWORD", PW)
    assert auth.page_kwargs() == {"http_credentials": {"username": USER, "password": PW}}
    monkeypatch.delenv("APP_PASSWORD")
    f = tmp_path / "pw"
    f.write_text(PW + "\n")
    monkeypatch.setenv("APP_PASSWORD_FILE", str(f))
    assert auth.credentials() == {"username": USER, "password": PW}
    monkeypatch.delenv("APP_USERNAME")
    assert auth.page_kwargs() == {}


def test_experiment_self_url_follows_port(monkeypatch):
    from app.api.experiments import exp_cfg
    monkeypatch.setenv("PORT", "9123")
    assert exp_cfg()["self_url"] == "http://127.0.0.1:9123"
