"""Browser smoke test: drives the real SPA in headless Chrome with a WAV file
as the fake microphone, holds Speaker A/B like a user, and reads the
browser-measured headline latency (speech end -> first audible sample).

    python -m eval.browser_smoke --wav en.wav --pipeline loopback --turns 3
    python -m eval.browser_smoke --wav en.wav --mode realtime --rt webrtc --turns 5
    python -m eval.browser_smoke --wav en.wav --mode realtime --turn-mode vad --switches 6

Release policy: PTT is released once the VAD has seen >= --release-silence-ms
of silence after speech, so the headline includes that release lag; the
script also prints H minus the release lag (system latency).
This is the seed of the M4 Playwright harness.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import statistics
from pathlib import Path

from playwright.async_api import async_playwright


async def run(a: argparse.Namespace) -> list[dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=a.chrome, headless=True,
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                  f"--use-file-for-fake-audio-capture={a.wav}", "--autoplay-policy=no-user-gesture-required"])
        page = await browser.new_page()
        page.on("console", lambda m: m.type in ("error", "warning") and print("console:", m.text))
        if a.block_webrtc:  # simulate a network that blocks the WebRTC SDP exchange (auto -> relay fallback)
            await page.route("https://api.openai.com/v1/realtime/calls*", lambda r: r.abort())
        q = f"pipeline={a.pipeline}&mode={a.mode}&rt={a.rt}&turn={a.turn_mode}"
        await page.goto(f"{a.url}/?{q}")
        await page.click("[data-testid=start]")
        await page.wait_for_function("window.__wb?.state?.sessionState === 'ready'", timeout=20000)
        print("providers:", json.dumps(await page.evaluate("window.__wb.state.providers")))
        results = []
        for i in range(a.turns):
            if a.turn_mode == "vad":
                results.append(await vad_turn(page, a, i + 1))
                continue
            speaker = a.speaker if a.speaker != "AB" else "AB"[i % 2]
            btn = await page.query_selector(f"[data-testid=ptt-{speaker}]")
            box = await btn.bounding_box()
            await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            # press during a silence gap so the turn captures a whole utterance of the looping file
            await page.wait_for_function(
                f"performance.now() - (window.__wb.lastVoiced ?? -1e9) > {a.press_silence_ms}", timeout=30000, polling=10)
            await page.mouse.down()
            t_down = await page.evaluate("performance.now()")
            # wait for speech, then for a silence gap after it
            await page.wait_for_function(f"(window.__wb.lastVoiced ?? 0) > {t_down} + {a.min_speech_ms}", timeout=30000)
            await page.wait_for_function(
                f"performance.now() - window.__wb.lastVoiced > {a.release_silence_ms}", timeout=30000, polling=10)
            t_up = await page.evaluate("performance.now()")
            await page.mouse.up()
            n = i + 1
            gate = None
            if a.mode == "realtime":
                # mic gating probe: sample the uplink state while the translation plays
                with contextlib.suppress(Exception):
                    await page.wait_for_function("window.__wb.diag().playing", timeout=5000, polling=20)
                    gate = await page.evaluate("window.__wb.diag()")
            await page.wait_for_function(
                f"(() => {{ const t = Object.values(window.__wb.state.turns).at(-1); return t && t.id === {n} && "
                f"['done','skipped','failed'].includes(t.status); }})()", timeout=a.turn_timeout * 1000)
            turn = await page.evaluate("Object.values(window.__wb.state.turns).at(-1)")
            row = _row(n, turn, t_up - turn["tSpeechEnd"])
            if gate is not None:
                row["gate_during_playback"] = {"playing": gate["playing"], "uplink_live": gate["uplinkLive"]}
            print(json.dumps(row, ensure_ascii=False))
            results.append(row)
            await page.wait_for_timeout(a.gap_ms)
        if a.dump_events:
            events = await page.evaluate("window.__wb.oaiEvents()")
            Path(a.dump_events).write_text(json.dumps(events, ensure_ascii=False, indent=1))
        print("diag after turns:", json.dumps(await page.evaluate("window.__wb.diag()")))
        if a.switches:
            modes = ["cascade", "realtime"] if a.mode == "realtime" else ["realtime", "cascade"]
            for k in range(a.switches):
                await page.click(f"[data-testid=mode-{modes[k % 2]}]")
                await page.wait_for_function("window.__wb?.state?.sessionState === 'ready'", timeout=20000)
                await page.wait_for_timeout(300)
            d = await page.evaluate("window.__wb.diag()")
            print(f"diag after {a.switches} mode switches:", json.dumps(d))
            print("LEAK CHECK", "PASS" if d["openTransports"] == 1 and d["micLive"] else "FAIL")
        errors = await page.evaluate("window.__wb.state.errors")
        if errors:
            print("UI errors:", json.dumps(errors, ensure_ascii=False))
        await browser.close()
        return results


def _row(n: int, turn: dict, lag: float | None) -> dict:
    h = turn.get("latencyMs")
    return {"turn": n, "status": turn["status"], "H_ms": h,
            "release_lag_ms": round(lag, 1) if lag is not None else None,
            "H_minus_lag_ms": round(h - lag, 1) if h is not None and lag is not None else None,
            "server_marks": turn["serverMarks"], "browser_marks": turn["browserMarks"],
            "source": " ".join(s["text"] for s in turn["source"].values()),
            "target": " ".join(s["text"] for s in turn["target"].values())}


async def vad_turn(page, a: argparse.Namespace, n: int) -> dict:
    """VAD mode: no button; the looping file provides speech + silence."""
    gate = None
    with contextlib.suppress(Exception):
        await page.wait_for_function(
            f"(() => {{ const t = Object.values(window.__wb.state.turns).find(t => t.id === {n}); return t && "
            "window.__wb.diag().playing; })()", timeout=a.turn_timeout * 1000, polling=20)
        gate = await page.evaluate("window.__wb.diag()")
    await page.wait_for_function(
        f"(() => {{ const t = Object.values(window.__wb.state.turns).find(t => t.id === {n}); return t && "
        f"['done','skipped','failed'].includes(t.status); }})()", timeout=a.turn_timeout * 1000)
    turn = await page.evaluate(f"Object.values(window.__wb.state.turns).find(t => t.id === {n})")
    row = _row(n, turn, None)
    if gate is not None:
        row["gate_during_playback"] = {"playing": gate["playing"], "uplink_live": gate["uplinkLive"]}
    print(json.dumps(row, ensure_ascii=False))
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8740")
    ap.add_argument("--wav", required=True)
    ap.add_argument("--pipeline", default="cascade", choices=["cascade", "loopback"])
    ap.add_argument("--mode", default="cascade", choices=["cascade", "realtime"])
    ap.add_argument("--rt", default="auto", choices=["webrtc", "relay", "auto"])
    ap.add_argument("--turn-mode", default="ptt", choices=["ptt", "vad"])
    ap.add_argument("--block-webrtc", action="store_true", help="abort the SDP POST to test the relay fallback")
    ap.add_argument("--switches", type=int, default=0, help="mode switches for the leak check")
    ap.add_argument("--dump-events", help="write raw realtime events to this JSON file")
    ap.add_argument("--speaker", default="A", choices=["A", "B", "AB"])
    ap.add_argument("--turns", type=int, default=3)
    ap.add_argument("--min-speech-ms", type=int, default=1500,
                    help="release only after voice was heard at least this long after the press")
    ap.add_argument("--release-silence-ms", type=int, default=700)
    ap.add_argument("--press-silence-ms", type=int, default=700)
    ap.add_argument("--gap-ms", type=int, default=500)
    ap.add_argument("--turn-timeout", type=int, default=30)
    ap.add_argument("--chrome", default="/usr/bin/google-chrome")
    a = ap.parse_args()
    rows = asyncio.run(run(a))
    hs = [r["H_ms"] for r in rows if r["H_ms"] is not None]
    sys_l = [r["H_minus_lag_ms"] for r in rows if r["H_minus_lag_ms"] is not None]
    if hs:
        extra = f" | H-minus-release-lag median={statistics.median(sys_l):.0f} ms" if sys_l else ""
        print(f"SUMMARY n={len(hs)}/{len(rows)} H median={statistics.median(hs):.0f} ms "
              f"min={min(hs):.0f} max={max(hs):.0f}{extra}")


if __name__ == "__main__":
    main()
