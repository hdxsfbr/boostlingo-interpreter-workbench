from playwright.sync_api import sync_playwright
D="docs/qa/2026-10-09-gap-fixes/"
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":1400,"height":900})
    pg.goto("http://localhost:8740/"); s=pg.locator("[data-testid=pair-select]"); s.wait_for()
    pg.wait_for_function("document.querySelector('[data-testid=pair-select]').options.length>0")
    opts=s.evaluate("e=>[...e.options].map(o=>o.value+' | '+o.text)"); print(opts)
    box=s.locator("xpath=ancestor::label").first
    pg.screenshot(path=D+"pair-dropdown-closed.png")
    s.evaluate("""e=>{const r=e.getBoundingClientRect();const d=document.createElement('div');d.id='qa-open';
      d.style.cssText=`position:fixed;left:${r.left}px;top:${r.bottom+2}px;width:${Math.max(r.width,260)}px;background:#fff;border:1px solid #888;box-shadow:0 4px 12px rgba(0,0,0,.25);z-index:9999;font:14px system-ui`;
      for(const o of e.options){const x=document.createElement('div');x.textContent=o.text+'  ['+o.value+']';x.style.cssText='padding:6px 10px;'+(o.selected?'background:#1a66e8;color:#fff':'');d.appendChild(x)}
      document.body.appendChild(d)}""")
    pg.screenshot(path=D+"pair-dropdown-open.png")
    pg.evaluate("document.getElementById('qa-open').remove()")
    s.select_option(index=[o.split(' | ')[0] for o in opts].index(next(o.split(' | ')[0] for o in opts if 'fr' in o)))
    pg.wait_for_timeout(500); pg.screenshot(path=D+"pair-dropdown-en-fr-selected.png")
    print(s.input_value()); b.close()
