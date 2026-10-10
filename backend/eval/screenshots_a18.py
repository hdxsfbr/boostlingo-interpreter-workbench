"""A18/A19 screenshots: a latency tooltip, the Latency card after a cascade run with a
speculative/long turn, and the Docs tab (index + an inner page with an image).

    python -m eval.screenshots_a18 [--url http://localhost:8740] [--chrome PATH]

Prints each turn's marks (JSON) so the early stages can be checked. About a cent.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from playwright.async_api import async_playwright

from eval import auth, harness


async def main(a: argparse.Namespace) -> None:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    us = harness.load_set(SimpleNamespace(utterances=None, ids=a.ids, dirs="en,es", per_size=0, sizes=None))
    order = {u: i for i, u in enumerate(a.ids.split(","))}
    us.sort(key=lambda u: order[u["id"]])
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, executable_path=a.chrome or None, args=["--autoplay-policy=no-user-gesture-required"])
        ctx = await b.new_context(viewport={"width": 1280, "height": 800}, **auth.page_kwargs())
        page = await ctx.new_page()

        async def serve(route):
            await route.fulfill(body=(harness.FIXTURES[0] / route.request.url.rsplit("/", 1)[-1]).read_bytes(), content_type="audio/wav")
        await page.route("**/fixtures/*.wav", serve)

        async def shot(name: str, el=None) -> None:
            await page.evaluate("document.fonts.ready")
            await (el or page).screenshot(path=str(out / f"{name}.png"))
            print("wrote", out / f"{name}.png")

        await page.goto(f"{a.url}/?source=file&mode=cascade&pair=en-es")
        await page.click("[data-testid=start]")
        await page.wait_for_function("window.__wb?.state?.sessionState === 'ready'", timeout=20000)
        ha = SimpleNamespace(record=None, release_silence_ms=450, turn_timeout=40)
        for u in us:
            await harness.ptt_turn(page, ha, u)
        turns = await page.evaluate("Object.values(window.__wb.state.turns).map(t => ({id: t.id, src: t.src, segs: Object.keys(t.source).length, mtSegs: Object.keys(t.target).length, "
                                    "latency: t.latencyMs, browser: t.browserMarks, server: t.serverMarks}))")
        for t in turns:
            print(json.dumps(t))
        # the latency card shows the last turn: make the long (speculative) one last
        await page.mouse.move(5, 5)
        card = await page.query_selector("[data-testid=metrics]")
        await page.set_viewport_size({"width": 1280, "height": 1100})
        await shot("latency-card-speculative", card)
        await page.focus("[data-testid=metrics] [data-term=mt_first_token]")  # keyboard focus shows the tooltip
        await shot("tooltip-focus-mt-first-token", card)
        await page.hover("[data-testid=metrics] th [data-term=p50]")
        await shot("tooltip-hover-p50", card)
        await page.set_viewport_size({"width": 1280, "height": 800})
        await page.click("[data-testid=stop]")
        await page.click("[data-testid=tab-docs]")
        await page.wait_for_selector("[data-testid=docs-page-index]")
        await shot("docs-index-1280")
        await page.click("[data-testid=docs-page-index] a[href*='02-interpreter']")
        await page.wait_for_selector("[data-testid=docs-page-02-interpreter] img")
        await page.evaluate("document.querySelector('[data-testid=docs-page-02-interpreter] img').scrollIntoView({block: 'center'})")
        await page.wait_for_function("[...document.querySelectorAll('.doc img')].every(i => i.complete && i.naturalWidth > 0)")
        print("url after in-tab link:", page.url)
        await shot("docs-02-interpreter-image-1280")
        dl = await ctx.new_page()
        await dl.goto(f"{a.url}/?tab=docs&page=05-understanding-the-numbers")
        await dl.wait_for_selector("[data-testid=docs-page-05-understanding-the-numbers]")
        print("deep link ok:", await dl.title())
        await b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8740")
    ap.add_argument("--out", default=str(harness.ROOT / "docs/design/redress/relay/after/a18-a19"))
    ap.add_argument("--ids", default="en-s01,es-m01,en-l01")
    ap.add_argument("--chrome")
    asyncio.run(main(ap.parse_args()))
