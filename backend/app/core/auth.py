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

Only GET /healthz is open, and it returns {"status": "ok"} and nothing else.
With the variables unset the gate is off (local dev); a loud warning is logged
if that happens on a hosted platform (PORT / RAILWAY_* set).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from collections.abc import Awaitable, Callable, MutableMapping
from http.cookies import CookieError, SimpleCookie
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger("app.auth")

COOKIE = "wb_session"
COOKIE_TTL_S = 12 * 3600
OPEN_PATHS = {"/healthz"}
REALM = 'Basic realm="Interpreter Workbench", charset="UTF-8"'

Scope = MutableMapping[str, Any]
ASGIApp = Callable[[Scope, Callable, Callable], Awaitable[None]]


def credentials_from_env(env: dict[str, str] | None = None) -> tuple[str, str] | None:
    env = dict(os.environ) if env is None else env
    user, pw = env.get("APP_USERNAME", ""), env.get("APP_PASSWORD", "")
    if user and pw:
        return user, pw
    hosted = [k for k in env if k == "PORT" or k.startswith("RAILWAY_")]
    if hosted:
        log.warning("!!! PASSWORD GATE OFF on what looks like a hosted deployment (%s set): anyone with the URL "
                    "can use the app and spend the API keys. Set APP_USERNAME and APP_PASSWORD. !!!",
                    ", ".join(sorted(hosted)[:3]))
    return None


class AuthGate:
    def __init__(self, app: ASGIApp, username: str, password: str, *, now: Callable[[], float] = time.time) -> None:
        self.app, self.now = app, now
        self._user, self._pw = username.encode(), password.encode()
        # the cookie key derives from the password: changing it invalidates every session
        self._key = hmac.new(self._pw, b"wb-session-v1|" + self._user, hashlib.sha256).digest()

    # ----- credentials
    def basic_ok(self, header: str | None) -> bool:
        if not header or not header.lower().startswith("basic "):
            return False
        try:
            raw = base64.b64decode(header[6:].strip(), validate=True)
        except ValueError:
            return False
        user, sep, pw = raw.partition(b":")
        ok_user = hmac.compare_digest(user, self._user)
        ok_pw = hmac.compare_digest(pw, self._pw)
        return bool(sep) and ok_user and ok_pw

    def make_cookie(self, exp: int | None = None) -> str:
        exp = exp or int(self.now()) + COOKIE_TTL_S
        sig = hmac.new(self._key, str(exp).encode(), hashlib.sha256).hexdigest()
        return f"{exp}.{sig}"

    def cookie_ok(self, value: str | None) -> bool:
        if not value or "." not in value:
            return False
        exp, _, sig = value.partition(".")
        if not exp.isdigit() or int(exp) < self.now():
            return False
        good = hmac.new(self._key, exp.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, good)

    # ----- ASGI
    async def __call__(self, scope: Scope, receive: Callable, send: Callable) -> None:
        kind = scope["type"]
        if kind not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        if kind == "http" and scope["path"] in OPEN_PATHS:
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        jar = SimpleCookie()
        try:
            jar.load(headers.get("cookie", ""))
        except (CookieError, ValueError):  # malformed cookie header -> treat as absent
            jar = SimpleCookie()
        has_cookie = COOKIE in jar and self.cookie_ok(jar[COOKIE].value)
        has_basic = self.basic_ok(headers.get("authorization"))
        if kind == "websocket":
            if not (has_cookie or has_basic) or not _same_origin(headers):
                return await _deny_ws(scope, send)
            return await self.app(scope, receive, send)
        if not (has_cookie or has_basic):
            return await _deny_http(send)
        if has_cookie:
            return await self.app(scope, receive, send)
        secure = _is_https(scope, headers)
        cookie = (f"{COOKIE}={self.make_cookie()}; Path=/; Max-Age={COOKIE_TTL_S}; HttpOnly; SameSite=Strict"
                  + ("; Secure" if secure else ""))

        async def send_with_cookie(msg: dict) -> None:
            if msg["type"] == "http.response.start":
                msg = {**msg, "headers": [*msg.get("headers", []), (b"set-cookie", cookie.encode())]}
            await send(msg)
        return await self.app(scope, receive, send_with_cookie)


def _is_https(scope: Scope, headers: dict[str, str]) -> bool:
    return scope.get("scheme") in ("https", "wss") or headers.get("x-forwarded-proto", "").split(",")[0] == "https"


def _same_origin(headers: dict[str, str]) -> bool:
    origin = headers.get("origin")
    if not origin:  # non-browser clients (harness over CDP still sends one; curl/tests may not)
        return True
    host = headers.get("x-forwarded-host") or headers.get("host", "")
    return urlsplit(origin).netloc.lower() == host.split(",")[0].strip().lower()


async def _deny_http(send: Callable) -> None:
    body = b'{"detail":"authentication required"}'
    await send({"type": "http.response.start", "status": 401,
                "headers": [(b"www-authenticate", REALM.encode()), (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


async def _deny_ws(scope: Scope, send: Callable) -> None:
    if "websocket.http.response" in scope.get("extensions", {}):  # uvicorn: a real HTTP 401 on the upgrade
        body = b'{"detail":"authentication required"}'
        await send({"type": "websocket.http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "websocket.http.response.body", "body": body})
    else:
        await send({"type": "websocket.close", "code": 1008})  # -> HTTP 403 on the upgrade
