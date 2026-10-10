"""A17: headless screenshots of every tab + the logged-out page (docs/design/redress/relay/after/).

    python -m eval.screenshots --url http://localhost:8740 --out ../docs/design/redress/relay/after [--turns 3] [--only interpreter]

Plays a few fixture utterances through a real cascade session (cents) so the Interpreter
shot has a transcript and latency, like the mockup. Credentials come from eval.auth (file/env).
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

from playwright.async_api import async_playwright

from eval import auth, harness

WIDTHS = [(1280, 800), (768, 1024), (390, 844)]


async def main(a: argparse.Namespace) -> None:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ids = "en-m01,es-m01,en-m02,es-m02"
    us = harness.interleave(harness.load_set(SimpleNamespace(utterances=None, ids=ids, dirs="en,es", per_size=0, sizes=None)))[: a.turns]
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, executable_path=a.chrome or None, args=["--autoplay-policy=no-user-gesture-required"])
        ctx = await b.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=1, **auth.page_kwargs())
        page = await ctx.new_page()

        async def serve(route):
            await route.fulfill(body=(harness.FIXTURES[0] / route.request.url.rsplit("/", 1)[-1]).read_bytes(), content_type="audio/wav")
        await page.route("**/fixtures/*.wav", serve)

        async def shot(name: str, full: bool = False) -> None:
            await page.evaluate("document.fonts.ready")
            await page.screenshot(path=str(out / f"{name}.png"), full_page=full)
            print("wrote", out / f"{name}.png")

        await page.goto(f"{a.url}/?source=file&mode=cascade&pair=en-es")
        await page.wait_for_selector("[data-testid=start]:not([disabled])")
        await shot("interpreter-idle-1280")
        if a.turns:
            await page.click("[data-testid=start]")
            await page.wait_for_function("window.__wb?.state?.sessionState === 'ready'", timeout=20000)
            ha = SimpleNamespace(record=None, release_silence_ms=450, turn_timeout=30)
            for u in us:
                await harness.ptt_turn(page, ha, u)
        await page.mouse.move(5, 5)
        for w, h in WIDTHS:
            await page.set_viewport_size({"width": w, "height": h})
            await shot(f"interpreter-{w}", full=w < 1280)
        await page.set_viewport_size({"width": 1280, "height": 800})
        if a.only == "interpreter":
            return await b.close()
        if a.turns:
            box = await (await page.query_selector("[data-testid=ptt-A]")).bounding_box()
            await page.mouse.move(box["x"] + 30, box["y"] + 30)
            await page.mouse.down()  # held state: SPEAKING (a sub-minimum turn, dropped)
            await page.wait_for_timeout(400)
            await shot("interpreter-speaking-1280")
            await page.mouse.up()
            await page.wait_for_timeout(1500)
            await page.click("[data-testid=stop]")
        for tab in ("review", "experiments"):
            await page.click(f"[data-testid=tab-{tab}]")
            await page.wait_for_timeout(1500)
            if tab == "review" and await page.query_selector("input[placeholder='e.g. andre']"):
                await page.fill("input[placeholder='e.g. andre']", "screenshot")  # name only; nothing is rated
                await page.click("text=Use")
                await page.wait_for_timeout(1500)
            for w, h in WIDTHS:
                await page.set_viewport_size({"width": w, "height": h})
                await shot(f"{tab}-{w}", full=w < 1280)
            await page.set_viewport_size({"width": 1280, "height": 800})
        # focus state evidence: keyboard-focus the Review tab button
        await page.click("[data-testid=tab-interpreter]")
        await page.keyboard.press("Tab")
        await page.focus("[data-testid=tab-review]")
        await page.keyboard.press("Shift+Tab")
        await page.keyboard.press("Tab")
        await shot("focus-visible-1280")
        lo = await ctx.new_page()
        await lo.goto(f"{a.url}/auth/logged-out")
        await lo.wait_for_selector("[data-testid=login-again]", state="visible")
        await lo.evaluate("document.fonts.ready")
        await lo.screenshot(path=str(out / "logged-out-1280.png"))
        print("wrote", out / "logged-out-1280.png")
        await b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8740")
    ap.add_argument("--out", default=str(harness.ROOT / "docs/design/redress/relay/after"))
    ap.add_argument("--turns", type=int, default=3)
    ap.add_argument("--only")
    ap.add_argument("--chrome", help="Chromium executable if the bundled one is missing")
    asyncio.run(main(ap.parse_args()))
