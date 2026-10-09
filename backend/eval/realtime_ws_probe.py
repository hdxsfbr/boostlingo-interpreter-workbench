"""Records a two-turn gpt-realtime-mini session over WS (dev fixture source). Key read from ~/.config/agentforge, never printed."""
import asyncio
import base64
import json
import pathlib
import sys
import time
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import websockets

from app.realtime.session_config import build_interpreter_session

k = pathlib.Path.home().joinpath('.config/agentforge/openai_api_key').read_text().strip()
def pcm_of(path):
    with wave.open(path) as w: return w.readframes(w.getnframes())
async def main():
    s = build_interpreter_session("en","es",model="gpt-realtime-mini")
    s.pop("model")
    s["audio"]["input"]["format"]={"type":"audio/pcm","rate":24000}
    s["audio"]["output"]["format"]={"type":"audio/pcm","rate":24000}
    out=[]
    async with websockets.connect("wss://api.openai.com/v1/realtime?model=gpt-realtime-mini", additional_headers={"Authorization": f"Bearer {k}"}, max_size=2**24) as ws:
        await ws.send(json.dumps({"type":"session.update","session":s}))
        for wavf in ["/tmp/bl/en_short.wav","/tmp/bl/es_short.wav"]:
            pcm=pcm_of(wavf)[48000:-48000*2]
            await ws.send(json.dumps({"type":"input_audio_buffer.clear"}))
            for i in range(0,len(pcm),9600):
                await ws.send(json.dumps({"type":"input_audio_buffer.append","audio":base64.b64encode(pcm[i:i+9600]).decode()}))
            t0=time.perf_counter()
            await ws.send(json.dumps({"type":"input_audio_buffer.commit"}))
            await ws.send(json.dumps({"type":"response.create"}))
            first=None
            while True:
                m=json.loads(await ws.recv())
                if m["type"]=="response.output_audio.delta":
                    if first is None: first=(time.perf_counter()-t0)*1000
                    m["delta"]=m["delta"][:16]+"...elided"
                out.append(m)
                if m["type"]=="error": print("ERR",m)
                if m["type"]=="response.done": break
            print(wavf, "first audio delta ms", round(first or -1))
    pathlib.Path("rt_ws_events.json").write_text(json.dumps(out,indent=1,ensure_ascii=False))
    from collections import Counter
    print(Counter(m["type"] for m in out))
    for m in out:
        if m["type"] in ("conversation.item.input_audio_transcription.completed","response.output_audio_transcript.done"): print(m["type"], m.get("transcript"))
        if m["type"]=="response.done": print("status", m["response"]["status"], "usage", m["response"].get("usage"), "output ids", [o.get("id") for o in m["response"].get("output",[])])
asyncio.run(main())
