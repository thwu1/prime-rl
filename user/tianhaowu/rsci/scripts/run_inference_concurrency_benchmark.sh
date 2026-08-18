#!/bin/bash
set -euo pipefail

cd /storage/home/tianhaowu/prime-rl

INFER_CONFIG=${1:?usage: run_inference_concurrency_benchmark.sh <inference.toml> <prompts.jsonl> <output-dir>}
PROMPTS=${2:?usage: run_inference_concurrency_benchmark.sh <inference.toml> <prompts.jsonl> <output-dir>}
OUTPUT_DIR=${3:?usage: run_inference_concurrency_benchmark.sh <inference.toml> <prompts.jsonl> <output-dir>}
shift 3
CONCURRENCY=("$@")
if [ "${#CONCURRENCY[@]}" -eq 0 ]; then
  CONCURRENCY=(8 16 32 64 128 256)
fi
mkdir -p "$OUTPUT_DIR"
export HF_HUB_OFFLINE=1
export OPENAI_API_KEY=unused
export PYTHONDONTWRITEBYTECODE=1
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

MODEL=$(uv run python - "$INFER_CONFIG" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    print(tomllib.load(handle)["model"]["name"])
PY
)

setsid uv run --no-sync inference \
  @ "$INFER_CONFIG" \
  --server.port 8000 \
  --output-dir "$OUTPUT_DIR/server" \
  --no-enable-prefix-caching \
  >"$OUTPUT_DIR/server.log" 2>&1 &
SERVER_PID=$!
cleanup() {
  kill -TERM -- "-$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

for attempt in $(seq 1 180); do
  status=$(curl -sS -o /dev/null --max-time 5 -w '%{http_code}' http://127.0.0.1:8000/health 2>/dev/null || true)
  if [ "$status" = 200 ]; then
    echo "inference server ready after $((attempt * 5)) seconds"
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "inference server exited before becoming ready" >&2
    tail -n 200 "$OUTPUT_DIR/server.log" >&2
    exit 1
  fi
  if [ "$attempt" = 180 ]; then
    echo "inference server was not ready within 15 minutes" >&2
    exit 1
  fi
  sleep 5
done

uv run --no-sync user/tianhaowu/rsci/inference_concurrency_benchmark.py \
  --model "$MODEL" \
  --prompts "$PROMPTS" \
  --output "$OUTPUT_DIR/results.json" \
  --concurrency "${CONCURRENCY[@]}"
