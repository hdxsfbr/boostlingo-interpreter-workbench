# Does a browser send cached Basic auth on WebSocket upgrades? (A15)

Run on 9 Oct 2026 with the official Playwright image (`mcr.microsoft.com/playwright/python:v1.55.0-noble`, `--network host`).

- `probe.py` (`uvicorn probe:app --port 8761`) is a basic-only server that reports whether each request carried `Authorization` / `Cookie`. `basic_vs_ws.py` loads it with HTTP credentials.
- `gate_run.py` runs the real app's gate (`APP_USERNAME=andre APP_PASSWORD=probe-pw uvicorn app.main:app --port 8762`). It checks WS and SSE after Basic login, and an anonymous page.

| Browser | fetch after Basic | WS upgrade after Basic (basic-only server) | Real gate: WS / SSE / anonymous |
|---|---|---|---|
| Chromium 140 (also Chrome 151) | Authorization sent | **Authorization sent** | ok / open / 401 |
| WebKit 26 (Safari engine) | Authorization sent | **nothing sent**: the upgrade would be rejected | ok / open / 401 |

Conclusion: cached Basic is not enough for WebSockets in Safari. The gate therefore sets a signed HttpOnly SameSite=Strict session cookie (Secure on HTTPS) on the first successful Basic request. Both engines send that cookie on the WS upgrade and on EventSource.
