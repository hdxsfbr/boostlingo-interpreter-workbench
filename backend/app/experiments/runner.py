"""Background experiment job (DESIGN A13).

REUSES the existing runner: each setup is one `python -m eval.harness` child
process (headless Chromium driving this app on 127.0.0.1 with fixture audio as
the mic), exactly as the M5 runs. The job tails the harness's streamed JSONL
for live progress (cost via eval.metrics.row_cost), then summarises with
eval.metrics.per_row + aggregate (latency, WER, chrF, $/min, failures).

One experiment at a time (others are refused with 409). Cancel kills the
harness's whole process tree (driver + Chromium), which closes the page's
WebSocket / WebRTC sessions, so no browser or provider session outlives it.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path

from app.experiments.config import SETUPS, ExperimentConfig, bench_langs
from app.experiments.store import ExperimentStore

log = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]
CommandFn = Callable[[str, list[str], ExperimentConfig, Path, str], list[str]]


class Busy(RuntimeError):
    pass


def harness_command(setup: str, ids: list[str], cfg: ExperimentConfig, out: Path, url: str) -> list[str]:
    s = SETUPS[setup]
    a, b = bench_langs()
    cmd = [sys.executable, "-u", "-m", "eval.harness", "--url", url, *s.args, "--ids", ",".join(ids),
           "--dirs", f"{a},{b}", "--pair", f"{a},{b}", "--repeat", str(cfg.passes), "--profile", setup, "--out", str(out), "--chrome", ""]
    if setup == "cascade-elevenlabs":
        cmd += ["--el-char-cap", "1400"]
    return cmd


def planned_order(ids: list[str], passes: int) -> list[str]:
    """Same order as eval.harness.interleave(load_set) * repeat."""
    langs = bench_langs()
    by = {k: [i for i in ids if i.startswith(f"{k}-")] for k in langs}
    out = []
    while any(by.values()):
        for k in langs:
            if by[k]:
                out.append(by[k].pop(0))
    return out * passes


def _descendants(root: int) -> set[int]:
    """All live processes below `root` (via /proc), so Chromium helpers that left the group are killed too."""
    kids: dict[int, list[int]] = {}
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            stat = (d / "stat").read_text()
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            continue
        kids.setdefault(ppid, []).append(int(d.name))
    out, todo = set(), [root]
    while todo:
        for c in kids.get(todo.pop(), []):
            if c not in out:
                out.add(c)
                todo.append(c)
    return out


def _alive(pid: int) -> bool:
    try:
        st = Path(f"/proc/{pid}/stat").read_text()
        return st.rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


class ExperimentRunner:
    def __init__(self, store: ExperimentStore, data_dir: Path, url: str, git_commit: str,
                 command: CommandFn = harness_command, metrics=None, poll_s: float = 0.3):
        self.store, self.data_dir, self.url, self.git_commit = store, data_dir, url, git_commit
        self.command, self._metrics, self.poll_s = command, metrics, poll_s
        self.current: dict | None = None
        self.subscribers: set[asyncio.Queue] = set()

    @property
    def metrics(self):
        if self._metrics is None:
            from eval import metrics
            self._metrics = metrics
        return self._metrics

    # ----- pub/sub for SSE
    def publish(self, ev: dict) -> None:
        for q in list(self.subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(ev)

    def busy(self) -> str | None:
        return self.current["id"] if self.current else None

    async def start(self, exp_id: str, cfg: ExperimentConfig) -> None:
        if self.current:
            raise Busy(f"experiment {self.current['id']} is running; wait for it or cancel it")
        self.current = {"id": exp_id, "proc": None, "cancel": False, "task": None}
        self.current["task"] = asyncio.create_task(self._run(exp_id, cfg))

    async def cancel(self, exp_id: str) -> bool:
        cur = self.current
        if not cur or cur["id"] != exp_id:
            return False
        cur["cancel"] = True
        await self._kill(cur.get("proc"))
        task = cur.get("task")
        if task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(asyncio.shield(task), timeout=30)
        return True

    async def _kill(self, proc) -> dict:
        if not proc or proc.returncode is not None:
            return {"orphans": 0}
        tree = _descendants(proc.pid) | {proc.pid}
        for sig in (signal.SIGTERM, signal.SIGKILL):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, sig)
            for pid in tree:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.kill(pid, sig)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=5)
            if not any(_alive(p) for p in tree - {proc.pid}) and proc.returncode is not None:
                break
        return {"orphans": sum(1 for p in tree if _alive(p))}

    # ----- the job
    async def _run(self, exp_id: str, cfg: ExperimentConfig) -> None:
        cur = self.current
        assert cur is not None
        t0 = time.time()
        ids = cfg.selected()
        total = len(ids) * cfg.passes * len(cfg.setups)
        prog = {"setup": None, "setup_index": 0, "setups": len(cfg.setups), "utterance": None, "done": 0,
                "total": total, "failures": 0, "cost_usd": 0.0, "p50_H_ms": None, "p50_by_setup": {}, "elapsed_s": 0}
        self.store.update(exp_id, status="running", started=t0, progress=prog)
        self.publish({"type": "status", "id": exp_id, "status": "running"})
        models: dict = {}
        errors: list[str] = []
        status = "done"
        cleanup = {"orphans": 0}
        try:
            for si, setup in enumerate(cfg.setups):
                if cur["cancel"]:
                    break
                prof = self.metrics.PROFILES.get(setup) or SETUPS[setup].models
                models[setup] = {"models": SETUPS[setup].models}
                order = planned_order(ids, cfg.passes)
                prog.update(setup=setup, setup_index=si + 1, utterance=order[0] if order else None)
                self._progress(exp_id, prog, t0)
                d = self.data_dir / "experiments" / exp_id
                d.mkdir(parents=True, exist_ok=True)
                out, logp = d / f"{setup}.jsonl", d / f"{setup}.log"
                out.write_text("")
                hs: list[float] = []
                with open(logp, "wb") as logf:  # noqa: ASYNC230 - child stdout sink, opened once per setup
                    proc = await asyncio.create_subprocess_exec(
                        *self.command(setup, ids, cfg, out, self.url), cwd=str(BACKEND_DIR), stdout=logf,
                        stderr=asyncio.subprocess.STDOUT, start_new_session=True,
                        env={**os.environ, "HOME": os.environ.get("HOME") or "/tmp", "PYTHONUNBUFFERED": "1"})
                    cur["proc"] = proc
                    pos, seen = 0, 0
                    while True:
                        finished = proc.returncode is not None
                        pos, rows = _read_new(out, pos)
                        for r in rows:
                            seen += 1
                            cost = float(self.metrics.row_cost(r, prof)) if r.get("usage") is not None else 0.0
                            self.store.add_turn(exp_id, setup, r, cost)
                            prog["done"] += 1
                            prog["cost_usd"] = round(prog["cost_usd"] + cost, 5)
                            if r.get("status") != "done":
                                prog["failures"] += 1
                            elif r.get("H_ms") is not None:
                                hs.append(r["H_ms"])
                            prog["p50_H_ms"] = round(statistics.median(hs)) if hs else None
                            prog["p50_by_setup"][setup] = prog["p50_H_ms"]
                            prog["utterance"] = order[seen] if seen < len(order) else None
                            self._progress(exp_id, prog, t0, last=r)
                        if finished:
                            break
                        with contextlib.suppress(asyncio.TimeoutError):
                            await asyncio.wait_for(proc.wait(), timeout=self.poll_s)
                    cur["proc"] = None
                providers = _providers(logp)
                if providers:
                    models[setup]["reported_providers"] = providers
                if proc.returncode not in (0, None) and not cur["cancel"]:
                    errors.append(f"{setup}: harness exited {proc.returncode}: {_tail(logp)}")
                elif seen == 0 and not cur["cancel"]:
                    errors.append(f"{setup}: no turns ({_tail(logp)})")
            if cur["cancel"]:
                status = "cancelled"
            elif errors and len(errors) == len(cfg.setups):
                status = "failed"
        except Exception as e:
            log.exception("experiment %s crashed", exp_id)
            errors.append(f"runner: {type(e).__name__}: {e}"[:400])
            status = "failed"
            cleanup = await self._kill(cur.get("proc"))
        finally:
            summary = await asyncio.to_thread(self._summarise, exp_id, cfg)
            prog["elapsed_s"] = round(time.time() - t0, 1)
            prog["utterance"] = None
            prog["cleanup"] = cleanup
            self.store.update(exp_id, status=status, finished=time.time(), summary=summary, models=models,
                              cost_usd=round(prog["cost_usd"], 5), error="; ".join(errors)[:2000], progress=prog)
            self.publish({"type": "status", "id": exp_id, "status": status, "progress": prog})
            self.current = None

    def _progress(self, exp_id: str, prog: dict, t0: float, last: dict | None = None) -> None:
        prog["elapsed_s"] = round(time.time() - t0, 1)
        self.store.update(exp_id, progress=prog)
        ev = {"type": "progress", "id": exp_id, **prog}
        if last:
            ev["last"] = {k: last.get(k) for k in ("id", "status", "H_ms", "H_minus_lag_ms", "source", "target")}
        self.publish(ev)

    def _summarise(self, exp_id: str, cfg: ExperimentConfig) -> list[dict]:
        out = []
        by: dict[str, list[dict]] = {}
        for t in self.store.turns(exp_id, full=True):
            by.setdefault(t["setup"], []).append(t["row"])
        for setup in cfg.setups:
            rows = by.get(setup) or []
            if not rows:
                continue
            prof = self.metrics.PROFILES.get(setup) or SETUPS[setup].models
            self.metrics.per_row(rows, prof)
            out.append(self.metrics.aggregate(setup, rows, prof))
        return out


def _read_new(path: Path, pos: int) -> tuple[int, list[dict]]:
    try:
        with open(path, "rb") as f:
            f.seek(pos)
            data = f.read()
    except OSError:
        return pos, []
    rows, consumed = [], 0
    for line in data.split(b"\n")[:-1]:  # only complete lines
        consumed += len(line) + 1
        if line.strip():
            with contextlib.suppress(ValueError):
                rows.append(json.loads(line))
    return pos + consumed, rows


def _tail(p: Path, n: int = 3) -> str:
    try:
        lines = [x for x in p.read_text(errors="replace").splitlines() if x.strip() and not x.startswith("console:")]
    except OSError:
        return ""
    return " | ".join(lines[-n:])[:400]


def _providers(p: Path) -> dict | None:
    try:
        for line in p.read_text(errors="replace").splitlines():
            if line.startswith("providers: "):
                return json.loads(line[len("providers: "):])
    except (OSError, ValueError):
        return None
    return None
