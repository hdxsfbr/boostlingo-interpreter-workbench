"""A16 logout check in Chromium and WebKit (Playwright). Never prints the password.

    APP_USERNAME=andre APP_PASSWORD_FILE=... python logout_check.py https://host
"""
import asyncio
import base64
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

URL = sys.argv[1].rstrip("/")
USER = os.environ.get("APP_USERNAME", "andre")
PW = Path(os.environ["APP_PASSWORD_FILE"]).read_text().strip()
GOOD = "Basic " + base64.b64encode(f"{USER}:{PW}".encode()).decode()
FETCH = "async (p) => (await fetch(p, {cache: 'no-store'})).status"


async def engine(p, name: str) -> list[tuple[str, bool]]:
    out = []
    b = await getattr(p, name).launch(headless=True)
    ctx = await b.new_context()
    pg = await ctx.new_page()
    await ctx.set_extra_http_headers({"Authorization": GOOD})  # log in once (the "prompt")
    r = await pg.goto(URL + "/")
    await ctx.set_extra_http_headers({})  # from here on, only what the browser kept (the cookie)
    out.append(("login: / 200", r.status == 200))
    await pg.wait_for_selector("[data-testid=logout]", timeout=15000)
    out.append(("Logout button shown (gate on)", True))
    out.append(("cookie session: /api/health 200", await pg.evaluate(FETCH, "/api/health") == 200))
    old = next(c["value"] for c in await ctx.cookies() if c["name"] == "wb_session")
    await pg.click("[data-testid=logout]")
    await pg.wait_for_url("**/auth/logged-out", timeout=15000)
    await pg.wait_for_selector("[data-testid=logout-status][data-done='1']", timeout=15000)
    out.append(("logged-out page shown", "Logged out" in await pg.content()))
    out.append(("cookie removed from the browser", not any(c["name"] == "wb_session" for c in await ctx.cookies())))
    for path in ("/api/health", "/api/languages", "/api/experiments"):
        out.append((f"after logout: {path} 401", await pg.evaluate(FETCH, path) == 401))
    r = await pg.goto(URL + "/")
    hdrs = await r.all_headers()
    challenge = hdrs.get("www-authenticate", "")
    print(f"{name:8} info  reload status={r.status} challenge={bool(challenge)}")
    out.append(("reload /: 401 with a Basic challenge (prompts again)", r.status == 401 and "basic" in challenge.lower()))
    replay = await ctx.request.get(URL + "/api/health", headers={"Cookie": f"wb_session={old}"})
    out.append(("old cookie replayed: 401 (revoked server-side)", replay.status == 401))
    probe = await ctx.request.get(URL + "/api/health", headers={
        "Authorization": "Basic " + base64.b64encode(b"logged-out:x").decode()})
    out.append(("bogus logout creds: 401, no challenge, no cookie",
                probe.status == 401 and "www-authenticate" not in probe.headers and "set-cookie" not in probe.headers))
    evil = await ctx.request.post(URL + "/auth/logout", headers={"Origin": "https://evil.example"})
    out.append(("cross-site logout POST: 403", evil.status == 403))
    await b.close()
    return out


async def main() -> int:
    ok = True
    async with async_playwright() as p:
        for name in ("chromium", "webkit"):
            for label, passed in await engine(p, name):
                ok &= passed
                print(f"{name:8} {'PASS' if passed else 'FAIL'} {label}")
    return 0 if ok else 1


sys.exit(asyncio.run(main()))
