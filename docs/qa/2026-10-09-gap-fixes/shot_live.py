# Two brief Realtime sessions (default, then ?rt_model=gpt-realtime-mini), PTT mode, fake mic, no talking.
import json, re, time
from playwright.sync_api import sync_playwright
D = "docs/qa/2026-10-09-gap-fixes/"
out = []
def red(s): return re.sub(r'"value"\s*:\s*"[^"]+"', '"value": "[REDACTED]"', s)
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
    ctx = b.new_context(viewport={"width": 1400, "height": 900}, permissions=["microphone"])
    for q in ["", "?rt_model=gpt-realtime-mini"]:
        pg = ctx.new_page()
        pg.goto("http://localhost:8740/" + q)
        pg.locator("[data-testid=mode-realtime]").click()
        pg.locator("[data-testid=pair-select]").wait_for()
        with pg.expect_response(lambda r: "/api/realtime/session" in r.url) as ri:
            pg.locator("[data-testid=start]").click()
        r = ri.value
        t0 = time.time()
        out.append(f"### UI page: http://localhost:8740/{q}  (Realtime mode, Start session)\n"
                   f"POST /api/realtime/session request body: {r.request.post_data}\n"
                   f"HTTP {r.status} response: {red(r.text())}\n")
        pg.locator("[data-testid=stop]").wait_for(timeout=15000)
        dis = pg.locator("[data-testid=pair-select]").is_disabled()
        out.append(f"pair-select disabled while running: {dis}\n")
        if q == "":
            pg.wait_for_function("!document.body.innerText.includes('connecting ·')", timeout=10000)
            st = pg.evaluate("document.body.innerText.match(/(\\w+) · realtime/)?.[0]")
            out.append(f"status at screenshot: {st}\n")
            pg.locator("[data-testid=pair-select]").hover(force=True); pg.wait_for_timeout(1200)
            pg.screenshot(path=D + "pair-dropdown-locked-live.png")
        pg.locator("[data-testid=stop]").click()
        out.append(f"session length ~{time.time()-t0:.1f}s, then Stop session\n\n")
        pg.close()
    b.close()
open("/tmp/rt_ui.txt", "w").write("".join(out))
