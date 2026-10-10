# syntax=docker/dockerfile:1
# ---- frontend build ----
FROM node:24-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
COPY contract/ /contract/
COPY docs/user-guide/ /docs/user-guide/
RUN npm run build

# ---- python deps ----
FROM python:3.12-slim AS py
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/backend
COPY backend/pyproject.toml ./
RUN mkdir app && touch app/__init__.py && pip install . && pip uninstall -y interpreter-workbench

# ---- tests (make test-docker): backend pytest + frontend vitest, no network/keys ----
FROM py AS test
COPY --from=web /usr/local/bin/node /usr/local/bin/node
COPY backend/ /app/backend/
COPY config/ /app/config/
COPY contract/ /app/contract/
# benchmark data the Review/Experiments/language tests read (REPO_ROOT/docs/benchmarks)
COPY docs/benchmarks/blind/ /app/docs/benchmarks/blind/
COPY docs/benchmarks/results/m5/results.json /app/docs/benchmarks/results/m5/results.json
COPY docs/benchmarks/results/m5/raw/ /app/docs/benchmarks/results/m5/raw/
COPY docs/benchmarks/utterances.yaml /app/docs/benchmarks/utterances.yaml
COPY --from=web /web /app/frontend
COPY docs/user-guide/ /app/docs/user-guide/
RUN pip install -e '.[dev]'
CMD ["sh", "-c", "cd /app/backend && pytest -q && cd /app/frontend && node node_modules/vitest/vitest.mjs run"]

# ---- runtime ----
FROM py AS runtime
# A13 Experiments tab: the eval runner (Playwright + headless Chromium + metrics deps)
# runs inside the app container, driving the app itself on 127.0.0.1.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install "playwright>=1.45" "jiwer>=3" "sacrebleu>=2.4" "whisper-normalizer>=0.0.10" \
 && python -m playwright install --with-deps --only-shell chromium \
 && chmod -R a+rX /ms-playwright
COPY backend/ /app/backend/
RUN pip install --no-deps .
COPY config/ /app/config/
COPY --from=web /web/dist /app/static
# A12 Review tab: blind clips + sheet/key (key stays server-side) and M5 results
COPY docs/benchmarks/blind/ /app/bench/blind/
COPY docs/benchmarks/results/m5/results.json /app/bench/results/m5/results.json
COPY docs/benchmarks/results/m5/raw/ /app/bench/results/m5/raw/
# eval/ resolves ROOT=/app: utterances under /app/docs, fixtures + ledger under /app/data -> /data
COPY docs/benchmarks/utterances.yaml /app/docs/benchmarks/utterances.yaml
RUN ln -s /data /app/data
ARG GIT_COMMIT=unknown
ENV CONFIG_DIR=/app/config STATIC_DIR=/app/static DATA_DIR=/data BENCH_DIR=/app/bench PYTHONUNBUFFERED=1 \
    GIT_COMMIT=${GIT_COMMIT}
EXPOSE 8740
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8740\")}/healthz',timeout=2).status==200 else 1)"
# $PORT on Railway (A15), 8740 locally. --forwarded-allow-ips: trust the platform proxy's X-Forwarded-Proto (Secure cookie)
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8740} --proxy-headers --forwarded-allow-ips='*'"]
