#!/bin/bash
set -euo pipefail

cd /storage/home/tianhaowu/prime-rl

CONFIG=${1:?usage: bash user/tianhaowu/rsci/scripts/run_eval.sh <eval-config.toml>}
export HF_HUB_OFFLINE=1
export OPENAI_API_KEY=unused
export PYTHONDONTWRITEBYTECODE=1
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

mapfile -t FIELDS < <(uv run python - "$CONFIG" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    config = tomllib.load(handle)
print(config["infer_config"])
print(config["eval"]["output_dir"])
print(config["eval"]["api_base_url"])
print(config.get("evaluator", "user/tianhaowu/rsci/eval.py"))
PY
)
INFER_CONFIG=${FIELDS[0]}
OUTPUT_DIR=${FIELDS[1]}
API_BASE_URL=${FIELDS[2]}
EVALUATOR=${FIELDS[3]}
mkdir -p "$OUTPUT_DIR"
uv run user/tianhaowu/rsci/snapshot_configs.py "$CONFIG"

setsid uv run inference @ "$INFER_CONFIG" >"$OUTPUT_DIR/server.log" 2>&1 &
SERVER_PID=$!
cleanup() {
  kill -TERM -- "-$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

HEALTH_URL=${API_BASE_URL%/v1}/health
for attempt in $(seq 1 180); do
  status=$(curl -sS -o /dev/null --max-time 5 -w '%{http_code}' "$HEALTH_URL" 2>/dev/null || true)
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

uv run "$EVALUATOR" "$CONFIG"
