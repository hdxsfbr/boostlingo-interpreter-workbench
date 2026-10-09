import asyncio, sys
from playwright.async_api import async_playwright
JS = """() => new Promise((res) => {
  const ws = new WebSocket(`ws://${location.host}/ws/realtime`);
  ws.onopen = () => ws.send('not json');
  ws.onmessage = (e) => res('ok: ' + e.data.slice(0, 40));
  ws.onerror = () => res('error'); setTimeout(() => res('timeout'), 5000);
})"""
SSE = """() => new Promise((res) => { const es = new EventSource('/api/experiments/m5-baseline/events');
  es.onmessage = (e) => { res('ok'); es.close(); }; es.onopen = () => { res('open'); es.close(); };
  es.onerror = () => { res('error'); es.close(); }; setTimeout(() => res('timeout'), 5000); })"""
async def main():
    async with async_playwright() as p:
        for name in ("chromium", "webkit"):
            b = await getattr(p, name).launch(headless=True)
            pg = await b.new_page(http_credentials={"username": "andre", "password": "probe-pw"})
            r = await pg.goto("http://127.0.0.1:8762/api/languages")
            ws = await pg.evaluate(JS); sse = await pg.evaluate(SSE)
            anon = await b.new_page()
            r2 = await anon.goto("http://127.0.0.1:8762/api/languages")
            print(name, "| page", r.status, "| WS", ws, "| SSE", sse, "| no-creds page", r2.status)
            await b.close()
asyncio.run(main())
