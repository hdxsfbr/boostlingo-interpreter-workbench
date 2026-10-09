"""Opt-in live provider tests (PRD CQ-3.5) are never collected unless LIVE_TESTS=1,
so `pytest`, CI and `make test-docker` cannot reach a real API."""
import os

collect_ignore_glob = [] if os.environ.get("LIVE_TESTS") == "1" else ["live/*"]
