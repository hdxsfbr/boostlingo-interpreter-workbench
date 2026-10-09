"""M5 error-state pass in the real SPA (DESIGN §6), no provider calls:

1. mic denied -> blocking banner with Retry; granting + Retry recovers;
2. insecure context (plain http on a non-localhost name) -> banner;
3. ElevenLabs selected while disabled -> one clear refusal banner;
4. a PTT turn with no speech -> skipped, no MT/TTS, session stays ready.

    python -m eval.error_pass --url http://127.0.0.1:8740
Rate limits, timeouts, empty transcripts/translations and provider
disconnects are covered by the fake-provider unit tests (tests/unit).
"""
from __future__ import annotations

import argparse
import asyncio
import json
from urllib.parse import urlparse

from playwright.async_api import async_playwright


async def main(a: argparse.Namespace) -> int:
    results: dict[str, str] = {}
    port = urlparse(a.url).port or 80
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=a.chrome, headless=True, args=[
            "--autoplay-policy=no-user-gesture-required", "--use-fake-device-for-media-stream",
            "--host-resolver-rules=MAP insecure.test 127.0.0.1"])
        # 1. mic denied, then recovered via Retry
        ctx = await b.new_context(permissions=[])
        page = await ctx.new_page()
        await page.goto(f"{a.url}/?mode=cascade")
        await page.click("[data-testid=start]")
        try:
            await page.wait_for_selector("[data-testid=error-mic_denied]", timeout=10000)
            retry = page.locator("[data-testid=error-mic_denied] button", has_text="Retry")
            ok_banner = await retry.count() == 1
            await ctx.grant_permissions(["microphone"], origin=a.url)
            await retry.click()
            await page.wait_for_function("window.__wb?.state?.sessionState === 'ready'", timeout=20000)
            results["mic_denied"] = "PASS: blocking banner + Retry; recovered to ready" if ok_banner else "FAIL: no Retry"
        except Exception as e:  # noqa: BLE001
            results["mic_denied"] = f"FAIL: {str(e)[:120]}"
        await ctx.close()
        # 2. insecure context
        ctx = await b.new_context()
        page = await ctx.new_page()
        await page.goto(f"http://insecure.test:{port}/?mode=cascade")
        await page.click("[data-testid=start]")
        try:
            await page.wait_for_selector("[data-testid=error-insecure_context]", timeout=10000)
            results["insecure_context"] = "PASS: banner shown"
        except Exception as e:  # noqa: BLE001
            results["insecure_context"] = f"FAIL: {str(e)[:120]}"
        await ctx.close()
        # 3. ElevenLabs refused while disabled (no ElevenLabs call is possible)
        ctx = await b.new_context(permissions=["microphone"])
        page = await ctx.new_page()
        await page.goto(f"{a.url}/?mode=cascade&tts=elevenlabs")
        await page.click("[data-testid=start]")
        try:
            await page.wait_for_function("window.__wb?.state?.errors?.length > 0", timeout=15000)
            errs = await page.evaluate("window.__wb.state.errors.map(e => e.code + ': ' + e.message)")
            results["elevenlabs_disabled"] = f"PASS: {len(errs)} banner(s): {errs[0][:110]}"
        except Exception as e:  # noqa: BLE001
            results["elevenlabs_disabled"] = f"FAIL: {str(e)[:120]}"
        await ctx.close()
        # 4. PTT turn without speech (file source: -60 dBFS noise floor, below the VAD threshold)
        ctx = await b.new_context()
        page = await ctx.new_page()
        await page.goto(f"{a.url}/?mode=cascade&source=file")
        await page.click("[data-testid=start]")
        await page.wait_for_function("window.__wb?.state?.sessionState === 'ready'", timeout=20000)
        btn = page.locator("[data-testid=ptt-A]")
        await btn.hover()
        await page.mouse.down()
        await page.wait_for_timeout(1500)
        await page.mouse.up()
        await page.wait_for_timeout(2500)
        st = await page.evaluate("({turns: Object.values(window.__wb.state.turns).map(t => [t.status, t.reason]), "
                                 "state: window.__wb.state.sessionState, errors: window.__wb.state.errors.length})")
        ok = st["state"] == "ready" and st["errors"] == 0 and all(s != "done" for s, _ in st["turns"])
        results["silent_turn"] = f"{'PASS' if ok else 'FAIL'}: {json.dumps(st)}"
        await ctx.close()
        await b.close()
    for k, v in results.items():
        print(f"{k}: {v}")
    return 0 if all(v.startswith("PASS") for v in results.values()) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8740")
    ap.add_argument("--chrome", default="/usr/bin/google-chrome")
    raise SystemExit(asyncio.run(main(ap.parse_args())))
