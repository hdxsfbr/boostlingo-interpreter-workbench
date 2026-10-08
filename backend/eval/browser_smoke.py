"""Browser smoke test: drives the real SPA in headless Chrome with a WAV file
as the fake microphone, holds Speaker A/B like a user, and reads the
browser-measured headline latency (speech end -> first audible sample).

    python -m eval.browser_smoke --wav en.wav --pipeline loopback --turns 3

Release policy: PTT is released once the VAD has seen >= --release-silence-ms
of silence after speech, so the headline includes that release lag; the
script also prints H minus the release lag (system latency).
This is the seed of the M4 Playwright harness.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics

from playwright.async_api import async_playwright


async def run(a: argparse.Namespace) -> list[dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=a.chrome, headless=True,
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                  f"--use-file-for-fake-audio-capture={a.wav}", "--autoplay-policy=no-user-gesture-required"])
        page = await browser.new_page()
        page.on("console", lambda m: m.type in ("error", "warning") and print("console:", m.text))
        await page.goto(f"{a.url}/?pipeline={a.pipeline}")
        await page.click("[data-testid=start]")
        await page.wait_for_function("window.__wb?.state?.sessionState === 'ready'", timeout=15000)
        results = []
        for i in range(a.turns):
            speaker = a.speaker if a.speaker != "AB" else "AB"[i % 2]
            btn = await page.query_selector(f"[data-testid=ptt-{speaker}]")
            box = await btn.bounding_box()
            await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            await page.mouse.down()
            t_down = await page.evaluate("performance.now()")
            # wait for speech, then for a silence gap after it
            await page.wait_for_function(f"(window.__wb.lastVoiced ?? 0) > {t_down} + {a.min_speech_ms}", timeout=30000)
            await page.wait_for_function(
                f"performance.now() - window.__wb.lastVoiced > {a.release_silence_ms}", timeout=30000, polling=10)
            t_up = await page.evaluate("performance.now()")
            await page.mouse.up()
            n = i + 1
            await page.wait_for_function(
                f"(() => {{ const t = Object.values(window.__wb.state.turns).at(-1); return t && t.id === {n} && "
                f"['done','skipped','failed'].includes(t.status); }})()", timeout=a.turn_timeout * 1000)
            turn = await page.evaluate("Object.values(window.__wb.state.turns).at(-1)")
            lag = t_up - turn["tSpeechEnd"]
            h = turn.get("latencyMs")
            row = {"turn": n, "status": turn["status"], "H_ms": h, "release_lag_ms": round(lag, 1),
                   "H_minus_lag_ms": round(h - lag, 1) if h is not None else None,
                   "server_marks": turn["serverMarks"], "browser_marks": turn["browserMarks"],
                   "source": " ".join(s["text"] for s in turn["source"].values()),
                   "target": " ".join(s["text"] for s in turn["target"].values())}
            print(json.dumps(row, ensure_ascii=False))
            results.append(row)
            await page.wait_for_timeout(a.gap_ms)
        errors = await page.evaluate("window.__wb.state.errors")
        if errors:
            print("UI errors:", json.dumps(errors, ensure_ascii=False))
        await browser.close()
        return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8740")
    ap.add_argument("--wav", required=True)
    ap.add_argument("--pipeline", default="cascade", choices=["cascade", "loopback"])
    ap.add_argument("--speaker", default="A", choices=["A", "B", "AB"])
    ap.add_argument("--turns", type=int, default=3)
    ap.add_argument("--min-speech-ms", type=int, default=1500)
    ap.add_argument("--release-silence-ms", type=int, default=700)
    ap.add_argument("--gap-ms", type=int, default=500)
    ap.add_argument("--turn-timeout", type=int, default=30)
    ap.add_argument("--chrome", default="/usr/bin/google-chrome")
    a = ap.parse_args()
    rows = asyncio.run(run(a))
    hs = [r["H_ms"] for r in rows if r["H_ms"] is not None]
    sys_l = [r["H_minus_lag_ms"] for r in rows if r["H_minus_lag_ms"] is not None]
    if hs:
        print(f"SUMMARY n={len(hs)} H median={statistics.median(hs):.0f} ms max={max(hs):.0f} | "
              f"H-minus-release-lag median={statistics.median(sys_l):.0f} ms")


if __name__ == "__main__":
    main()
