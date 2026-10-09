"""Credentials for eval scripts against a password-gated app (A15).

From APP_USERNAME + APP_PASSWORD (what the in-app Experiments runner inherits),
or APP_USERNAME + APP_PASSWORD_FILE (remote runs; the password never touches argv).
Nothing here prints the password.
"""
from __future__ import annotations

import base64
import os
import urllib.request
from pathlib import Path


def credentials() -> dict | None:
    user = os.environ.get("APP_USERNAME", "")
    pw = os.environ.get("APP_PASSWORD", "")
    if not pw and os.environ.get("APP_PASSWORD_FILE"):
        pw = Path(os.environ["APP_PASSWORD_FILE"]).expanduser().read_text().strip()
    return {"username": user, "password": pw} if user and pw else None


def page_kwargs() -> dict:
    """For browser.new_page(...): Chromium answers the 401 challenge, then the app's session cookie covers WS/SSE."""
    c = credentials()
    return {"http_credentials": c} if c else {}


def urlopen(req: str | urllib.request.Request, timeout: float = 10):
    if isinstance(req, str):
        req = urllib.request.Request(req)
    c = credentials()
    if c:
        tok = base64.b64encode(f"{c['username']}:{c['password']}".encode()).decode()
        req.add_header("Authorization", f"Basic {tok}")
    return urllib.request.urlopen(req, timeout=timeout)
