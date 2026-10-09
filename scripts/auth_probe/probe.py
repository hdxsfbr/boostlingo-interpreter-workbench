import json
PAGE = b"""<html><body><script>
const ws = new WebSocket(`ws://${location.host}/ws`);
ws.onmessage = (e) => { document.title = 'WS:' + e.data; };
ws.onerror = () => { document.title = 'WS:error'; };
ws.onclose = (e) => { if (!document.title.startsWith('WS:{')) document.title = 'WS:closed ' + e.code; };
fetch('/sse-probe').then(r => r.text()).then(t => { window.sseProbe = t; });
</script></body></html>"""
async def app(scope, receive, send):
    h = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    info = {"auth": "authorization" in h, "cookie": "cookie" in h}
    if scope["type"] == "websocket":
        await receive()
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.send", "text": json.dumps(info)})
        await send({"type": "websocket.close", "code": 1000})
        return
    if scope["type"] != "http":
        return
    if "authorization" not in h and scope["path"] == "/":
        await send({"type": "http.response.start", "status": 401, "headers": [(b"www-authenticate", b'Basic realm="x"')]})
        await send({"type": "http.response.body", "body": b""}); return
    body = PAGE if scope["path"] == "/" else json.dumps(info).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/html" if scope["path"] == "/" else b"application/json")]})
    await send({"type": "http.response.body", "body": body})
