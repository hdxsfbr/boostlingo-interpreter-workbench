"""App-wide password gate (DESIGN A15).

When APP_USERNAME and APP_PASSWORD are both set, every HTTP and WebSocket
route needs either
  * HTTP Basic credentials (compared in constant time), or
  * the `wb_session` cookie that a successful Basic request sets: an HMAC-signed
    expiry, HttpOnly, SameSite=Strict, Secure on HTTPS.
The cookie is what WebSockets and EventSource rely on: browsers do not reliably
attach cached Basic credentials to WS upgrades (WebKit/Safari does not), but
they do send same-origin cookies. WS upgrades must also come from the same
origin (cross-site WebSocket hijacking guard).

Only GET /healthz (returns {"status": "ok"} and nothing else) and the static
GET /auth/logged-out page are open. POST /auth/logout (same-origin only) expires
the cookie and revokes its nonce server-side; the revocation set is persisted
to DATA_DIR/auth_revoked.json so it survives restarts (A16).
With the variables unset the gate is off (local dev); a loud warning is logged
if that happens on a hosted platform (PORT / RAILWAY_* set).
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from collections.abc import Awaitable, Callable, MutableMapping
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger("app.auth")

COOKIE = "wb_session"
COOKIE_TTL_S = 12 * 3600
OPEN_PATHS = {"/healthz", "/auth/logged-out"}
LOGOUT_PATH = "/auth/logout"
LOGOUT_USER = b"logged-out"  # the logout page's deliberately bogus Basic user: 401 without a challenge (no prompt loop)
REALM = 'Basic realm="Interpreter Workbench", charset="UTF-8"'

Scope = MutableMapping[str, Any]
ASGIApp = Callable[[Scope, Callable, Callable], Awaitable[None]]


def credentials_from_env(env: dict[str, str] | None = None, *, warn: bool = True) -> tuple[str, str] | None:
    env = dict(os.environ) if env is None else env
    user, pw = env.get("APP_USERNAME", ""), env.get("APP_PASSWORD", "")
    if user and pw:
        return user, pw
    hosted = [k for k in env if k == "PORT" or k.startswith("RAILWAY_")]
    if hosted and warn:
        log.warning("!!! PASSWORD GATE OFF on what looks like a hosted deployment (%s set): anyone with the URL "
                    "can use the app and spend the API keys. Set APP_USERNAME and APP_PASSWORD. !!!",
                    ", ".join(sorted(hosted)[:3]))
    return None


class AuthGate:
    def __init__(self, app: ASGIApp, username: str, password: str, *, now: Callable[[], float] = time.time,
                 revoked_path: Path | None = None) -> None:
        self.app, self.now = app, now
        self.revoked_path = revoked_path
        self._lock = threading.Lock()
        self.revoked: dict[str, int] = self._load_revoked()
        self._user, self._pw = username.encode(), password.encode()
        # the cookie key derives from the password: changing it invalidates every session
        self._key = hmac.new(self._pw, b"wb-session-v1|" + self._user, hashlib.sha256).digest()

    # ----- credentials
    @staticmethod
    def _basic_parts(header: str | None) -> tuple[bytes, bytes, bool] | None:
        if not header or not header.lower().startswith("basic "):
            return None
        try:
            raw = base64.b64decode(header[6:].strip(), validate=True)
        except ValueError:
            return None
        user, sep, pw = raw.partition(b":")
        return user, pw, bool(sep)

    def is_logout_probe(self, header: str | None) -> bool:
        parts = self._basic_parts(header)
        return bool(parts) and parts[0] == LOGOUT_USER and parts[0] != self._user

    def basic_ok(self, header: str | None) -> bool:
        parts = self._basic_parts(header)
        if not parts:
            return False
        user, pw, sep = parts
        ok_user = hmac.compare_digest(user, self._user)
        ok_pw = hmac.compare_digest(pw, self._pw)
        return bool(sep) and ok_user and ok_pw

    def make_cookie(self, exp: int | None = None) -> str:
        exp = exp or int(self.now()) + COOKIE_TTL_S
        nonce = secrets.token_urlsafe(12)
        sig = hmac.new(self._key, f"{exp}.{nonce}".encode(), hashlib.sha256).hexdigest()
        return f"{exp}.{nonce}.{sig}"

    def _parse(self, value: str | None) -> tuple[int, str] | None:
        """(exp, nonce) of a well-signed, unexpired cookie; None otherwise (revocation not checked)."""
        parts = (value or "").split(".")
        if len(parts) != 3 or not parts[0].isdigit():
            return None
        exp, nonce, sig = parts
        good = hmac.new(self._key, f"{exp}.{nonce}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good) or int(exp) < self.now():
            return None
        return int(exp), nonce

    def cookie_ok(self, value: str | None) -> bool:
        p = self._parse(value)
        return bool(p) and p[1] not in self.revoked

    # ----- revocation (logout)
    def _load_revoked(self) -> dict[str, int]:
        if not self.revoked_path:
            return {}
        try:
            data = json.loads(self.revoked_path.read_text())
            return {str(k): int(v) for k, v in data.items() if int(v) >= self.now()}
        except (OSError, ValueError, AttributeError):
            return {}

    def revoke(self, value: str | None) -> bool:
        p = self._parse(value)
        if not p:
            return False
        with self._lock:
            now = self.now()
            self.revoked = {n: e for n, e in self.revoked.items() if e >= now}  # prune expired
            self.revoked[p[1]] = p[0]
            if self.revoked_path:
                with contextlib.suppress(OSError):
                    self.revoked_path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = self.revoked_path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(self.revoked))
                    os.replace(tmp, self.revoked_path)
        return True

    # ----- ASGI
    async def __call__(self, scope: Scope, receive: Callable, send: Callable) -> None:
        kind = scope["type"]
        if kind not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        if kind == "http" and scope["path"] in OPEN_PATHS and scope["method"] in ("GET", "HEAD"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        jar = SimpleCookie()
        try:
            jar.load(headers.get("cookie", ""))
        except (CookieError, ValueError):  # malformed cookie header -> treat as absent
            jar = SimpleCookie()
        raw_cookie = jar[COOKIE].value if COOKIE in jar else None
        if kind == "http" and scope["path"] == LOGOUT_PATH:
            return await self._logout(scope, headers, raw_cookie, send)
        has_cookie = self.cookie_ok(raw_cookie)
        has_basic = self.basic_ok(headers.get("authorization"))
        if kind == "websocket":
            if not (has_cookie or has_basic) or not _same_origin(headers):
                return await _deny_ws(scope, send)
            return await self.app(scope, receive, send)
        if not (has_cookie or has_basic):
            # the logout page's bogus credentials get a 401 without a challenge: replaces the
            # browser's cached Basic entry where it can, and never pops a prompt (no loop)
            return await _deny_http(send, challenge=not self.is_logout_probe(headers.get("authorization")))
        cookie = None if has_cookie else _cookie_header(self.make_cookie(), COOKIE_TTL_S, _is_https(scope, headers))

        async def send_gated(msg: dict) -> None:
            if msg["type"] == "http.response.start":
                hs = list(msg.get("headers", []))
                # gated content must be revalidated through the gate: without this, browsers served
                # index.html from heuristic cache after logout (seen on Railway, A16)
                if not any(k.lower() == b"cache-control" for k, _ in hs):
                    hs.append((b"cache-control", b"private, no-cache"))
                if cookie:
                    hs.append((b"set-cookie", cookie.encode()))
                msg = {**msg, "headers": hs}
            await send(msg)
        return await self.app(scope, receive, send_gated)


    async def _logout(self, scope: Scope, headers: dict[str, str], raw_cookie: str | None, send: Callable) -> None:
        if scope["method"] != "POST":
            return await _respond(send, 405, b'{"detail":"POST only"}', [(b"allow", b"POST")])
        if not headers.get("origin") or not _same_origin(headers):  # CSRF: SameSite=Strict + a same-origin Origin
            return await _respond(send, 403, b'{"detail":"cross-origin logout refused"}')
        revoked = self.revoke(raw_cookie)
        expire = _cookie_header("", 0, _is_https(scope, headers)) + "; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
        body = json.dumps({"logged_out": True, "revoked": revoked}).encode()
        return await _respond(send, 200, body, [(b"set-cookie", expire.encode()), (b"cache-control", b"no-store")])


def _cookie_header(value: str, max_age: int, secure: bool) -> str:
    return (f"{COOKIE}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict" + ("; Secure" if secure else ""))


async def _respond(send: Callable, status: int, body: bytes, extra: list | None = None) -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                            *(extra or [])]})
    await send({"type": "http.response.body", "body": body})


def _is_https(scope: Scope, headers: dict[str, str]) -> bool:
    return scope.get("scheme") in ("https", "wss") or headers.get("x-forwarded-proto", "").split(",")[0] == "https"


def _same_origin(headers: dict[str, str]) -> bool:
    origin = headers.get("origin")
    if not origin:  # non-browser clients (harness over CDP still sends one; curl/tests may not)
        return True
    host = headers.get("x-forwarded-host") or headers.get("host", "")
    return urlsplit(origin).netloc.lower() == host.split(",")[0].strip().lower()


async def _deny_http(send: Callable, challenge: bool = True) -> None:
    body = b'{"detail":"authentication required"}'
    extra = [(b"www-authenticate", REALM.encode())] if challenge else []
    await _respond(send, 401, body, [*extra, (b"cache-control", b"no-store")])


async def _deny_ws(scope: Scope, send: Callable) -> None:
    if "websocket.http.response" in scope.get("extensions", {}):  # uvicorn: a real HTTP 401 on the upgrade
        body = b'{"detail":"authentication required"}'
        await send({"type": "websocket.http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "websocket.http.response.body", "body": body})
    else:
        await send({"type": "websocket.close", "code": 1008})  # -> HTTP 403 on the upgrade


# Open, static, no secrets. Overwrites the browser's cached Basic credentials with a bogus
# pair (the server answers 401 *without* a challenge, so no prompt and no loop), then offers
# a fresh login. "Log in again" goes to "/", whose 401 challenge prompts for the password.
LOGGED_OUT_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Logged out · AI Interpreter Workbench</title>
<style>body{font:16px system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 1rem}</style></head>
<body><h1>Logged out</h1><p id="status" data-testid="logout-status">Clearing saved credentials&hellip;</p>
<p><a href="/" data-testid="login-again">Log in again</a></p>
<script>
(async () => {
  const s = document.getElementById("status");
  try {
    // an explicit (bogus) Authorization header replaces any cached Basic credentials on this request;
    // credentials: "omit" keeps cookies out, so this request can never re-authenticate the browser
    await fetch("/api/health", {headers: {Authorization: "Basic " + btoa("logged-out:x")}, cache: "no-store",
                                credentials: "omit"});
  } catch (e) { /* offline: the cookie is already gone */ }
  s.textContent = "You are logged out. Close the browser to be sure no saved password is reused.";
  s.dataset.done = "1";
})();
</script></body></html>
"""
