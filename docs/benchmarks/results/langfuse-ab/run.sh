#!/bin/bash
# Langfuse off vs on A/B (A20), same method as recording-ab: cascade default, PTT 450 ms,
# arms alternate off,on,off,on; plus a few realtime-mini turns per round. One image.
# Keys are mounted read-only as files (never in argv/env values).
set -u
cd ~/code/boostlingo-interpreter-workbench
IMG=${IMG:-interpreter-workbench:lf}; TAG=${TAG:-lf}
CF=~/.config/agentforge
IDS=en-s01,en-s02,en-s03,en-s04,en-s05,en-s06,en-s07,en-m01,es-s01,es-s02,es-s03,es-s04,es-s05,es-m01
RT_IDS=en-s03,es-s03,en-s04
start() { docker run -d --rm --name wb-ab-$1 --env-file .env $3 -e ELEVENLABS_API_KEY_FILE=/dev/null \
  --user "$(id -u):$(id -g)" -p 127.0.0.1:$2:8740 -v "$PWD/data:/data" $IMG >/dev/null; }
LF="-e LANGFUSE_ENABLED=1 -e LANGFUSE_HOST=https://us.cloud.langfuse.com \
 -e LANGFUSE_PUBLIC_KEY_FILE=/run/secrets/lf_pk -e LANGFUSE_SECRET_KEY_FILE=/run/secrets/lf_sk \
 -v $CF/langfuse_public_key:/run/secrets/lf_pk:ro -v $CF/langfuse_secret_key:/run/secrets/lf_sk:ro"
start off 8781 ""; start on 8782 "$LF"
for p in 8781 8782; do for i in $(seq 1 30); do curl -fsS http://127.0.0.1:$p/healthz >/dev/null 2>&1 && break; sleep 1; done; done
cd backend
for r in 1 2; do for arm in off on; do
  p=$([ $arm = off ] && echo 8781 || echo 8782)
  /tmp/oaisdk/bin/python -u -m eval.harness --url http://127.0.0.1:$p --mode cascade --ids $IDS \
    --profile lf-$arm --out /tmp/bl/ab/$TAG-$arm-r$r.jsonl > /tmp/bl/ab/$TAG-$arm-r$r.log 2>&1
  /tmp/oaisdk/bin/python -u -m eval.harness --url http://127.0.0.1:$p --mode realtime --rt-model gpt-realtime-mini --ids $RT_IDS \
    --profile lf-rt-$arm --out /tmp/bl/ab/$TAG-rt-$arm-r$r.jsonl > /tmp/bl/ab/$TAG-rt-$arm-r$r.log 2>&1
  echo "done $arm r$r cascade $(grep -c '"status": "done"' /tmp/bl/ab/$TAG-$arm-r$r.jsonl) rt $(grep -c '"status": "done"' /tmp/bl/ab/$TAG-rt-$arm-r$r.jsonl)"
done; done
sleep 5
docker logs wb-ab-on > /tmp/bl/ab/$TAG-on.server.log 2>&1
docker stop wb-ab-off wb-ab-on >/dev/null
echo ALLDONE
