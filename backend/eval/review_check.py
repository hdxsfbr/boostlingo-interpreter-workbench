"""Headless check of the Review tab (DESIGN A12). No provider calls.

    cd backend && /tmp/oaisdk/bin/python -m eval.review_check --url http://127.0.0.1:8740

1. Rater `andre`: the blind set shows 48/48 complete; Results cells equal
   docs/benchmarks/blind/results.md (overall + both directions).
2. Scratch rater: no variant names on the rating screen, keyboard round trip
   (5,4,3 + Enter saves and advances; Tab; Space plays/pauses), Back shows the
   saved scores, resume after reload, results locked, a failed save shows an
   alert. Then the scratch rater's ratings are deleted via the API.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

from eval import auth

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = ("realtime", "cascade-openai", "cascade-haiku", "cascade-elevenlabs")
SCRATCH = "zz-scratch-check"


def expected_cells() -> dict[tuple[str, str], list[str]]:
    """{(variant, scope): [adequacy, fluency, naturalness, composite]} from results.md."""
    out, scope = {}, None
    for line in (ROOT / "docs/benchmarks/blind/results.md").read_text().splitlines():
        if line.startswith("## "):
            h = line[3:]
            scope = "all" if h.startswith("Overall") else (h.split()[0] if h.split()[0] in ("en->es", "es->en") else None)
        elif scope and line.startswith("| ") and line.split("|")[1].strip() in VARIANTS:
            c = [x.strip() for x in line.strip("|").split("|")]
            out[(c[0], scope)] = c[1:5]
    return out


async def main(url: str, chrome: str) -> bool:
    ok = True

    def check(cond: bool, what: str) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + what)

    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=chrome, headless=True, args=["--autoplay-policy=no-user-gesture-required"])
        page = await b.new_page(**auth.page_kwargs())
        page.on("console", lambda m: m.type == "error" and print("console:", m.text))

        async def use(name: str) -> None:
            await page.fill("[data-testid=rater-name]", name)
            await page.click("[data-testid=rater-use]")

        await page.goto(f"{url}/?tab=review")
        await use("andre")
        prog = page.locator("[data-testid=set-progress-blind-m5]")
        await prog.wait_for()
        check((await prog.inner_text()).strip() == "48/48 · complete", f"andre blind set complete ({await prog.inner_text()})")
        await page.click("[data-testid=results-blind-m5]")
        await page.locator("[data-testid=results-view]").wait_for()
        exp = expected_cells()
        bad = 0
        for (v, scope), cells in exp.items():
            tds = await page.locator(f"[data-testid='result-{v}-{scope}'] td").all_inner_texts()
            got = tds[2:5] + [tds[5]]
            if got != cells:
                bad += 1
                print("  mismatch", v, scope, got, "!=", cells)
        check(bad == 0 and len(exp) == 12, f"Results equal results.md ({len(exp)} variant x scope rows)")

        # ----- scratch rater
        await page.click("[data-testid=review-back-to-sets]")
        await use(SCRATCH)
        await page.wait_for_function("document.querySelector('[data-testid=set-progress-blind-m5]')?.innerText.startsWith('0/48')")
        await page.click("[data-testid=open-blind-m5]")
        await page.locator("[data-testid=rate-view]").wait_for()
        body = (await page.inner_text("body")).lower()
        check(not any(v in body for v in ("cascade", "realtime", "haiku", "elevenlabs")), "no variant names while rating blind")
        check((await page.inner_text("[data-testid=rate-pos]")) == "1 of 48", "starts at clip 1")
        au = page.locator("[data-testid=rate-audio]")
        await page.wait_for_function("document.querySelector('[data-testid=rate-audio]').readyState >= 2", timeout=10000)
        before = await au.evaluate("a => a.paused")
        await page.keyboard.press(" ")
        await page.wait_for_timeout(300)
        check(await au.evaluate("a => a.paused") != before, "Space toggles play/pause")
        for k in ("5", "4"):
            await page.keyboard.press(k)
        await page.keyboard.press("Tab")  # focus wraps from naturalness to accuracy
        await page.keyboard.press("3")    # overwrite accuracy -> 3, focus to fluency
        await page.keyboard.press("Tab")  # -> naturalness
        await page.keyboard.press("2")
        await page.keyboard.press("Enter")
        await page.wait_for_function("document.querySelector('[data-testid=rate-pos]')?.innerText === '2 of 48'")
        check((await page.inner_text("[data-testid=rate-progress]")).startswith("1/48"), "Enter saved and advanced (1/48)")
        await page.click("[data-testid=rate-back]")
        await page.wait_for_function("document.querySelector('[data-testid=rate-pos]')?.innerText === '1 of 48'")
        on = [await page.locator(f"[data-testid=score-{d}-{v}]").get_attribute("class") for d, v in
              (("adequacy", 3), ("fluency", 4), ("naturalness", 2))]
        check(all(c == "on" for c in on), "Back shows saved scores A3 F4 N2")
        await page.click("[data-testid=view-results]")
        await page.locator("[data-testid=results-locked]").wait_for()
        check(True, "results locked for an incomplete blind set")
        # resume after a reload: first clip without all three scores (clip 2)
        await page.goto(f"{url}/?tab=review")
        await page.click("[data-testid=open-blind-m5]")
        await page.wait_for_function("document.querySelector('[data-testid=rate-pos]')?.innerText === '2 of 48'")
        check(True, "resume opens clip 2 after reload")
        # failed save -> visible alert, stays on the clip
        await page.route("**/rating", lambda r: r.abort())
        for k in ("4", "4", "4"):
            await page.keyboard.press(k)
        await page.keyboard.press("Enter")
        err = page.locator("[data-testid=save-error]")
        await err.wait_for()
        check("Save failed" in await err.inner_text() and await page.inner_text("[data-testid=rate-pos]") == "2 of 48",
              "failed save shows an alert and keeps the clip")
        await page.unroute("**/rating")
        await b.close()
    return ok


def cleanup(url: str, ok: bool) -> int:
    def check(cond: bool, what: str) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + what)

    req = urllib.request.Request(f"{url}/api/review/sets/blind-m5/ratings?rater={SCRATCH}", method="DELETE")
    deleted = json.loads(auth.urlopen(req).read())["deleted"]
    left = json.loads(auth.urlopen(f"{url}/api/review/sets/blind-m5?rater={SCRATCH}").read())["ratings"]
    check(deleted == 1 and left == {}, f"scratch ratings deleted ({deleted})")
    andre = json.loads(auth.urlopen(f"{url}/api/review/sets/blind-m5?rater=andre").read())["progress"]
    check(andre["done"] == 48, "andre still 48/48")
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8740")
    ap.add_argument("--chrome", default="/usr/bin/google-chrome")
    a = ap.parse_args()
    sys.exit(cleanup(a.url, asyncio.run(main(a.url, a.chrome))))
