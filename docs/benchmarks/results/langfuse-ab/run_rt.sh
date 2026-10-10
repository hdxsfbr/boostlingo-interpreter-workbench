#!/bin/bash
# Follow-up: realtime-mini only, more turns, arms alternate off,on x3 (A20).
set -u
cd ~/code/boostlingo-interpreter-workbench
IMG=${IMG:-interpreter-workbench:lf}; TAG=${TAG:-lfrt}; CF=~/.config/agentforge
RT_IDS=en-s03,es-s03,en-s04,es-s04,en-s05,es-s05
start() { docker run -d --rm --name wb-ab-$1 --env-file .env $3 -e ELEVENLABS_API_KEY_FILE=/dev/null \
  --user "$(id -u):$(id -g)" -p 127.0.0.1:$2:8740 -v "$PWD/data:/data" $IMG >/dev/null; }
LF="-e LANGFUSE_ENABLED=1 -e LANGFUSE_HOST=https://us.cloud.langfuse.com \
 -e LANGFUSE_PUBLIC_KEY_FILE=/run/secrets/lf_pk -e LANGFUSE_SECRET_KEY_FILE=/run/secrets/lf_sk \
 -v $CF/langfuse_public_key:/run/secrets/lf_pk:ro -v $CF/langfuse_secret_key:/run/secrets/lf_sk:ro"
start off 8781 ""; start on 8782 "$LF"
for p in 8781 8782; do for i in $(seq 1 30); do curl -fsS http://127.0.0.1:$p/healthz >/dev/null 2>&1 && break; sleep 1; done; done
cd backend
for r in 1 2 3; do for arm in on off; do
  p=$([ $arm = off ] && echo 8781 || echo 8782)
  /tmp/oaisdk/bin/python -u -m eval.harness --url http://127.0.0.1:$p --mode realtime --rt-model gpt-realtime-mini --ids $RT_IDS \
    --profile lf-rt-$arm --out /tmp/bl/ab/$TAG-rt-$arm-r$r.jsonl > /tmp/bl/ab/$TAG-rt-$arm-r$r.log 2>&1
  echo "done $arm r$r rt $(grep -c '"status": "done"' /tmp/bl/ab/$TAG-rt-$arm-r$r.jsonl)"
done; done
docker stop wb-ab-off wb-ab-on >/dev/null
echo ALLDONE
