import json,re,collections
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox"])
    pg=b.new_page(viewport={"width":1280,"height":800},user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36")
    css={}
    def onr(r):
        if r.request.resource_type=="stylesheet" or r.url.split("?")[0].endswith(".svg"):
            try: css[r.url]=r.text()
            except: pass
    pg.on("response",onr)
    pg.goto("https://boostlingo.com/",wait_until="networkidle",timeout=60000)
    pg.wait_for_timeout(3000)
    pg.screenshot(path="desktop-1280.png")
    pg.mouse.wheel(0,20000);pg.wait_for_timeout(2000)
    pg.screenshot(path="fullpage-1280.png",full_page=True)
    comp=pg.evaluate("""()=>{const q=(s)=>{const e=document.querySelector(s);if(!e)return null;const c=getComputedStyle(e);return {sel:s,text:(e.innerText||'').slice(0,60),color:c.color,bg:c.backgroundColor,font:c.fontFamily,size:c.fontSize,weight:c.fontWeight,radius:c.borderRadius}};
    const out=['body','h1','h2','h3','p','a','header','nav a','footer','button'].map(q);
    document.querySelectorAll('a[class*=btn],a[class*=button],.elementor-button,button').forEach((e,i)=>{if(i<8){const c=getComputedStyle(e);out.push({sel:'button#'+i+' .'+e.className,text:e.innerText.slice(0,40),color:c.color,bg:c.backgroundColor,font:c.fontFamily,radius:c.borderRadius})}});
    const logo=[...document.querySelectorAll('header img, header svg, a[class*=logo] img, img[alt*=oost]')].slice(0,5).map(e=>({tag:e.tagName,src:e.src||e.getAttribute('src')||'inline',alt:e.alt||''}));
    const imgs=[...document.images].slice(0,40).map(e=>e.src);
    return {out,logo,imgs,title:document.title,h:document.body.scrollHeight}}""")
    json.dump(comp,open("computed.json","w"),indent=1)
    import os;os.makedirs("assets",exist_ok=True)
    idx=[]
    for i,(u,t) in enumerate(css.items()):
        fn=f"assets/{i:02d}"+(".svg" if ".svg" in u else ".css");open(fn,"w").write(t);idx.append((fn,u))
    json.dump(idx,open("assets/index.json","w"),indent=1)
    b.close()
