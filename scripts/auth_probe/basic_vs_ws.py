import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        for name in ("chromium", "webkit"):
            try:
                b = await getattr(p, name).launch(headless=True)
            except Exception as e:
                print(name, "launch failed:", str(e).splitlines()[0]); continue
            pg = await b.new_page(http_credentials={"username": "u", "password": "p"})
            await pg.goto("http://127.0.0.1:8761/")
            await pg.wait_for_function("document.title.startsWith('WS:')", timeout=10000)
            await pg.wait_for_function("window.sseProbe", timeout=10000)
            print(name, b.version, "| WS upgrade:", (await pg.title())[3:], "| fetch:", await pg.evaluate("window.sseProbe"))
            await b.close()
asyncio.run(main())
