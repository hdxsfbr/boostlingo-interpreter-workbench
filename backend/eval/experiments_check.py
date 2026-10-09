"""Headless check of the Experiments tab (DESIGN A13) against a running app.
No experiment is started: the tab loads, the M5 baseline and the given
experiment appear in history with their summaries, the estimate updates, the
gpt-realtime warning shows, and a >$1 config asks for confirmation (dismissed).

    docker exec -e HOME=/tmp -w /app/backend boostlingo-interpreter-workbench-app-1 \
        python -m eval.experiments_check --chrome "" --exp <experiment id>
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


async def main(url: str, exp: str, chrome: str, results: str) -> bool:
    ok = True

    def check(cond: bool, what: str) -> None:
        nonlocal ok
        ok &= cond
        print("PASS" if cond else "FAIL", what)

    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=chrome or None, headless=True)
        page = await b.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(f"{url}/?tab=experiments")
        await page.wait_for_selector("[data-testid=exp-history] [data-testid=exp-row-m5-baseline]", timeout=10000)
        check(True, "tab loads, M5 baseline in history")
        check(await page.locator(f"[data-testid=exp-row-{exp}]").count() == 1, f"smoke experiment {exp} in history")
        await page.click("[data-testid=exp-open-m5-baseline]")
        await page.wait_for_selector("[data-testid=summary-row-realtime]")
        res = json.loads(await asyncio.to_thread(Path(results).read_text))
        for prof in res["profiles"]:
            row = await page.locator(f"[data-testid=summary-row-{prof['profile']}] td").all_inner_texts()
            want = (str(prof["H"]["p50"]), str(prof["H_minus_gap"]["p50"]), f"{prof['quality']['all']['chrF']:.1f}")
            check((row[2], row[4], row[9]) == want, f"baseline {prof['profile']}: H p50 / H-gap p50 / chrF {row[2]} / {row[4]} / {row[9]} == results.json")
        check(await page.locator("[data-testid=latency-chart] circle").count() > 300, "baseline latency chart drawn")
        await page.click(f"[data-testid=exp-open-{exp}]")
        await page.wait_for_selector(f"[data-testid=summary-{exp}] [data-testid=summary-row-cascade-openai]")
        check(await page.locator("[data-testid=exp-detail] .badge.status-done").count() == 1, "smoke detail: status done")
        r = await page.locator(f"[data-testid=summary-{exp}] [data-testid=summary-row-realtime-mini] td").all_inner_texts()
        check(r[1] == "6 / 6", f"smoke detail shows its own rows ({r[1]})")
        print("  smoke realtime-mini row:", r)
        await page.wait_for_selector("[data-testid=exp-estimate-total]")
        est0 = await page.inner_text("[data-testid=exp-estimate-total]")
        await page.click("[data-testid=exp-setup-realtime]")
        check(await page.locator("[data-testid=exp-warning-realtime]").count() == 1, "gpt-realtime cost warning shown")
        await page.click("[data-testid=exp-utt-full]")
        await page.fill("[data-testid=exp-passes]", "3")
        await page.wait_for_function(f"document.querySelector('[data-testid=exp-estimate-total]').innerText !== {json.dumps(est0)}")
        est1 = await page.inner_text("[data-testid=exp-estimate-total]")
        check(True, f"estimate updates: {est0} -> {est1}")
        await page.click("[data-testid=exp-run]")
        await page.wait_for_selector("[data-testid=exp-confirm]", timeout=5000)
        check(True, "above $1: confirmation asked before running")
        await page.click("[data-testid=exp-confirm] >> text=Cancel")
        check(await page.locator("[data-testid=exp-setup-cascade-elevenlabs]").is_disabled(), "ElevenLabs setup disabled (provider off)")
        await page.click(f"[data-testid=exp-row-{exp}] input[type=checkbox]")
        await page.click("[data-testid=exp-row-m5-baseline] input[type=checkbox]")
        await page.click("[data-testid=exp-compare-btn]")
        await page.wait_for_selector("[data-testid=exp-compare] tbody tr")
        check(await page.locator("[data-testid=exp-compare] tbody tr").count() >= 16, "compare view renders")
        await page.screenshot(path="/tmp/bl/exp_check.png", full_page=True)
        check(not errors, f"no page errors {errors[:2]}")
        await b.close()
    n = json.loads(await asyncio.to_thread(_get, f"{url}/api/experiments"))
    check(not any(e["status"] == "running" for e in n), "nothing left running")
    return ok


def _get(u: str) -> str:
    import urllib.request
    with urllib.request.urlopen(u, timeout=10) as r:
        return r.read().decode()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8740")
    ap.add_argument("--exp", required=True)
    ap.add_argument("--chrome", default="/usr/bin/google-chrome", help="'' = Playwright's bundled Chromium (in the container)")
    ap.add_argument("--results", default="/app/bench/results/m5/results.json")
    a = ap.parse_args()
    raise SystemExit(0 if asyncio.run(main(a.url, a.exp, a.chrome, a.results)) else 1)
