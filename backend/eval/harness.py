"""Benchmark harness (DESIGN §9): drives the real SPA in headless Chrome with
`?source=file`, plays each fixture from docs/benchmarks/utterances.yaml as the
microphone, and reads the browser-measured headline H (last voiced frame ->
first audible sample).

PTT release policy (DESIGN A2): the "user" releases 450 ms after the last
voiced frame; every row also carries H minus that release gap.

    python -m eval.harness --mode cascade --per-size 2 --out results.jsonl
    python -m eval.harness --mode realtime --rt webrtc --dirs en,es
    python -m eval.harness --mode realtime --turn-mode vad --vad-ms 300
    python -m eval.harness --mode cascade --soak-s 300          # NFR-2 soak

Fixtures come from `make fixtures` (data/fixtures/*.wav) and are served to the
page by Playwright request interception, so the app needs no extra route.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import time
from pathlib import Path

import yaml
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
SPEAKER = {"en": "A", "es": "B"}  # pair a=en, b=es
TERMINAL = "['done','skipped','failed']"


def load_set(a: argparse.Namespace) -> list[dict]:
    data = yaml.safe_load((ROOT / "docs" / "benchmarks" / "utterances.yaml").read_text())
    ids = {s for s in a.ids.split(",") if s}
    out = []
    for lang in a.dirs.split(","):
        seen: dict[str, int] = {}
        for u in data[lang]:
            if ids and u["id"] not in ids:
                continue
            if not ids and a.per_size and seen.get(u["size"], 0) >= a.per_size:
                continue
            if a.sizes and u["size"] not in a.sizes.split(","):
                continue
            seen[u["size"]] = seen.get(u["size"], 0) + 1
            out.append({**u, "lang": lang})
    return out


def interleave(items: list[dict]) -> list[dict]:
    """Alternate directions (A, B, A, ...) like a real two-party exchange."""
    by = {"en": [u for u in items if u["lang"] == "en"], "es": [u for u in items if u["lang"] == "es"]}
    out = []
    while by["en"] or by["es"]:
        for k in ("en", "es"):
            if by[k]:
                out.append(by[k].pop(0))
    return out


async def turns_after(page, n0: int) -> list[dict]:
    return await page.evaluate(f"Object.values(window.__wb.state.turns).filter(t => t.id > {n0})")


async def wait_idle(page, n0: int, timeout_s: float) -> None:
    """All turns since n0 are terminal and nothing is playing."""
    await page.wait_for_function(
        f"(() => {{ const ts = Object.values(window.__wb.state.turns).filter(t => t.id > {n0}); "
        f"return ts.length > 0 && ts.every(t => {TERMINAL}.includes(t.status)) && !window.__wb.diag().playing; }})()",
        timeout=timeout_s * 1000, polling=20)


async def ptt_turn(page, a, u: dict) -> dict:
    n0 = await page.evaluate("Object.values(window.__wb.state.turns).length ? Math.max(...Object.keys(window.__wb.state.turns).map(Number)) : 0")
    btn = await page.query_selector(f"[data-testid=ptt-{SPEAKER[u['lang']]}]")
    box = await btn.bounding_box()
    await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    await page.mouse.down()
    t_down = await page.evaluate("performance.now()")
    await page.evaluate("url => { window.__wb.__started = null; window.__play = window.__wb.playFile(url); }",
                        f"/fixtures/{u['id']}.wav")
    # The "user" releases 450 ms after the LAST voiced frame of the utterance (they
    # know when they are done), so in-sentence pauses do not cut the turn; trailing
    # file silence does not count either. speech_end_ms is precomputed with the
    # capture worklet's VAD rule (20 ms frames, RMS >= 0.012).
    end_ms = speech_end_ms(u["id"])
    await page.wait_for_function(
        f"(() => {{ const s = window.__wb.fileStartedAt?.(); const lv = window.__wb.lastVoiced ?? 0; "
        f"return s !== null && s > {t_down} - 1 && lv >= s + {end_ms} - 100 && performance.now() - lv > {a.release_silence_ms}; }})()",
        timeout=30000, polling=5)
    t_up = await page.evaluate("performance.now()")
    await page.mouse.up()
    await wait_idle(page, n0, a.turn_timeout)
    await page.evaluate("window.__play")  # the file's trailing silence has finished too
    ts = await turns_after(page, n0)
    return row(u, ts, t_up)


async def vad_turn(page, a, u: dict) -> dict:
    n0 = await page.evaluate("Object.values(window.__wb.state.turns).length ? Math.max(...Object.keys(window.__wb.state.turns).map(Number)) : 0")
    await page.evaluate("sp => window.__wb.setVadSpeaker(sp)", SPEAKER[u["lang"]])
    await page.evaluate("url => { window.__play = window.__wb.playFile(url); }", f"/fixtures/{u['id']}.wav")
    await page.evaluate("window.__play")
    try:
        await page.wait_for_function(f"Object.values(window.__wb.state.turns).some(t => t.id > {n0})", timeout=5000)
        # a split turn may still be pending when the file ends: wait for quiet, then idle
        await page.wait_for_timeout(a.vad_ms + 300)
        await wait_idle(page, n0, a.turn_timeout)
    except Exception:  # noqa: BLE001 - no turn detected
        return {**base(u), "status": "no_turn", "H_ms": None, "turns": 0}
    ts = await turns_after(page, n0)
    return row(u, ts, None)


_END_CACHE: dict[str, float] = {}


def speech_end_ms(uid: str, threshold: float = 0.012, frame: int = 480) -> float:
    """Offset of the last voiced 20 ms frame in the fixture (capture worklet rule)."""
    if uid not in _END_CACHE:
        import array
        import math
        import wave
        with wave.open(str(ROOT / "data" / "fixtures" / f"{uid}.wav")) as w:
            rate = w.getframerate()
            pcm = array.array("h", w.readframes(w.getnframes()))
        step = frame * rate // 24000
        last = 0
        for i in range(0, len(pcm) - step + 1, step):
            seg = pcm[i:i + step]
            rms = math.sqrt(sum(x * x for x in seg) / step) / 32768
            if rms >= threshold:
                last = i + step
        _END_CACHE[uid] = last * 1000 / rate
    return _END_CACHE[uid]


def base(u: dict) -> dict:
    return {"id": u["id"], "lang": u["lang"], "size": u["size"], "domain": u["domain"]}


def row(u: dict, ts: list[dict], t_up: float | None) -> dict:
    last = ts[-1]
    h = last.get("latencyMs")
    lag = (t_up - last["tSpeechEnd"]) if (t_up is not None and last.get("tSpeechEnd") is not None) else None
    r = {**base(u), "status": last["status"], "reason": last.get("reason"), "turns": len(ts), "H_ms": h,
         "release_lag_ms": round(lag, 1) if lag is not None else None,
         "H_minus_lag_ms": round(h - lag, 1) if (h is not None and lag is not None) else None,
         "first_H_ms": ts[0].get("latencyMs"),
         # cascade: when the LAST segment's audio would start (server mark after the final
         # commit + browser commit offset); excludes network/playout (~40-60 ms). Estimate.
         "tail_est_ms": _tail(last),
         "server_marks": last.get("serverMarks"), "browser_marks": last.get("browserMarks"),
         "source": " / ".join(" ".join(s["text"] for s in t["source"].values()) for t in ts),
         "target": " / ".join(" ".join(s["text"] for s in t["target"].values()) for t in ts),
         "reference": u["reference_translation"]}
    return r


def _tail(t: dict) -> float | None:
    sm, bm = t.get("serverMarks") or {}, t.get("browserMarks") or {}
    if "tail_tts_first_byte" in sm and "commit_sent" in bm:
        return round(sm["tail_tts_first_byte"] + bm["commit_sent"], 1)
    return None


def backend_rss_mb() -> float | None:
    try:
        out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"],
                             capture_output=True, text=True, timeout=10, check=False).stdout
        for line in out.splitlines():
            name, mem = line.split(" ", 1)
            if "workbench" in name or "interpreter" in name:
                v = mem.split("/")[0].strip()
                num = float(v.rstrip("KMGiB"))
                return num / 1024 if "KiB" in v else num * 1024 if "GiB" in v else num
    except Exception:  # noqa: BLE001
        return None
    return None


async def probe(page) -> dict:
    d = await page.evaluate("({diag: window.__wb.diag(), heap: performance.memory ? performance.memory.usedJSHeapSize : null, "
                            "errors: window.__wb.state.errors.length, state: window.__wb.state.sessionState})")
    d["backend_rss_mb"] = backend_rss_mb()
    return d


async def run(a: argparse.Namespace) -> list[dict]:
    items = interleave(load_set(a)) * a.repeat
    fixtures = ROOT / "data" / "fixtures"
    missing = [u["id"] for u in items if not (fixtures / f"{u['id']}.wav").exists()]
    if missing:
        raise SystemExit(f"missing fixtures {missing[:5]}...: run `make fixtures`")
    out = open(a.out, "w") if a.out else None  # noqa: SIM115, ASYNC230 - streamed line by line
    rows: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=a.chrome, headless=True,
                                          args=["--autoplay-policy=no-user-gesture-required", "--enable-precise-memory-info"])
        page = await browser.new_page()
        page.on("console", lambda m: m.type == "error" and print("console:", m.text))

        async def serve(route):
            name = route.request.url.rsplit("/", 1)[-1]
            await route.fulfill(body=(fixtures / name).read_bytes(), content_type="audio/wav")
        await page.route("**/fixtures/*.wav", serve)
        q = f"source=file&mode={a.mode}&rt={a.rt}&turn={a.turn_mode}&vad_ms={a.vad_ms}"
        q += "".join(f"&{k}={v}" for k, v in (("mt", a.mt), ("tts", a.tts)) if v)
        await page.goto(f"{a.url}/?{q}")
        await page.click("[data-testid=start]")
        await page.wait_for_function("['ready','error'].includes(window.__wb?.state?.sessionState)", timeout=20000)
        if await page.evaluate("window.__wb.state.sessionState") == "error":
            print("SESSION ERROR:", json.dumps(await page.evaluate("window.__wb.state.errors"), ensure_ascii=False))
            await browser.close()
            return []
        print("providers:", json.dumps(await page.evaluate("window.__wb.state.providers")))
        t0 = time.monotonic()
        i = 0
        while True:
            if a.soak_s:
                if time.monotonic() - t0 >= a.soak_s:
                    break
                u = items[i % len(items)]
            elif i >= len(items):
                break
            else:
                u = items[i]
            i += 1
            try:
                r = await (vad_turn(page, a, u) if a.turn_mode == "vad" else ptt_turn(page, a, u))
            except Exception as e:  # noqa: BLE001 - keep going, record the failure
                r = {**base(u), "status": "harness_error", "H_ms": None, "error": str(e)[:200]}
            r["n"] = i
            r["t_s"] = round(time.monotonic() - t0, 1)
            if a.soak_s and (i == 1 or i % a.probe_every == 0):
                r["probe"] = await probe(page)
            rows.append(r)
            line = json.dumps(r, ensure_ascii=False)
            if out:
                out.write(line + "\n")
                out.flush()
            short = {k: r.get(k) for k in ("n", "id", "status", "turns", "H_ms", "H_minus_lag_ms")}
            print(json.dumps(short, ensure_ascii=False), "|", r.get("source", "")[:60], "->", r.get("target", "")[:60])
            await page.wait_for_timeout(a.gap_ms)
        end = await probe(page)
        print("END PROBE:", json.dumps(end))
        errs = await page.evaluate("window.__wb.state.errors")
        if errs:
            print("UI errors:", json.dumps(errs, ensure_ascii=False))
        await browser.close()
    if out:
        out.close()
    return rows


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(q * (len(xs) - 1)))]


def summarize(rows: list[dict]) -> None:
    groups = [(lang, None) for lang in ("en", "es")] + [(None, sz) for sz in ("short", "medium", "long")] + [(None, None)]
    for lang, size in groups:
        rs = [r for r in rows if (lang is None or r["lang"] == lang) and (size is None or r["size"] == size)]
        hs = [r["H_ms"] for r in rs if r.get("H_ms") is not None and r["status"] == "done"]
        gl = [r["H_minus_lag_ms"] for r in rs if r.get("H_minus_lag_ms") is not None and r["status"] == "done"]
        if not hs:
            continue
        split = sum(1 for r in rs if r.get("turns", 1) > 1)
        msg = (f"SUMMARY {lang or size or 'all'}: n={len(hs)}/{len(rs)} H p50={statistics.median(hs):.0f} p90={pct(hs, .9):.0f} "
               f"max={max(hs):.0f}")
        if gl:
            msg += f" | H-gap p50={statistics.median(gl):.0f} p90={pct(gl, .9):.0f}"
        tl = [r["tail_est_ms"] for r in rs if r.get("tail_est_ms") is not None and r["status"] == "done"]
        if tl:
            msg += f" | tail_est p50={statistics.median(tl):.0f} p90={pct(tl, .9):.0f}"
        msg += f" | split={split}"
        print(msg)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8740")
    ap.add_argument("--mode", default="cascade", choices=["cascade", "realtime"])
    ap.add_argument("--rt", default="webrtc", choices=["webrtc", "relay", "auto"])
    ap.add_argument("--turn-mode", default="ptt", choices=["ptt", "vad"])
    ap.add_argument("--vad-ms", type=int, default=400, help="silence window (server_vad silence_duration_ms / cascade VAD)")
    ap.add_argument("--mt")
    ap.add_argument("--tts")
    ap.add_argument("--dirs", default="en,es")
    ap.add_argument("--sizes", default="")
    ap.add_argument("--per-size", type=int, default=0, help="first N utterances of each size per direction (0 = all)")
    ap.add_argument("--ids", default="")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--soak-s", type=int, default=0, help="loop the set for this many seconds (NFR-2 soak)")
    ap.add_argument("--probe-every", type=int, default=5)
    ap.add_argument("--release-silence-ms", type=int, default=450, help="DESIGN A2: fixed 450 ms PTT release")
    ap.add_argument("--gap-ms", type=int, default=600)
    ap.add_argument("--turn-timeout", type=int, default=40)
    ap.add_argument("--out")
    ap.add_argument("--chrome", default="/usr/bin/google-chrome")
    a = ap.parse_args()
    rows = asyncio.run(run(a))
    summarize(rows)


if __name__ == "__main__":
    main()
