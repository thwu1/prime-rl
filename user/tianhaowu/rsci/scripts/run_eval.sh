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

NODE_COUNT=${SLURM_NNODES:-1}
if [ "$NODE_COUNT" -eq 1 ]; then
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
  exit
fi

RUNTIME_DIR="$OUTPUT_DIR/runtime"
mkdir -p "$RUNTIME_DIR"
mapfile -t RUNTIME_FIELDS < <(uv run python - "$CONFIG" "$RUNTIME_DIR" "$NODE_COUNT" <<'PY'
import copy
import sys
import tomllib
from pathlib import Path

import tomli_w


source_path = Path(sys.argv[1])
runtime_dir = Path(sys.argv[2])
node_count = int(sys.argv[3])
with source_path.open("rb") as handle:
    eval_config = tomllib.load(handle)
infer_source = Path(eval_config["infer_config"])
with infer_source.open("rb") as handle:
    infer_config = tomllib.load(handle)

runtime_infer = runtime_dir / "inference.toml"
runtime_eval = runtime_dir / "eval.toml"
infer_config.setdefault("server", {})["host"] = "0.0.0.0"
infer_config["server"]["port"] = 8100
eval_config = copy.deepcopy(eval_config)
eval_config["infer_config"] = str(runtime_infer.resolve())
eval_config["eval"]["api_base_url"] = "http://127.0.0.1:8000/v1"
eval_config["eval"]["max_concurrent_prompts"] *= node_count
if "prompt_batch_size" in eval_config["eval"]:
    eval_config["eval"]["prompt_batch_size"] *= node_count

for path, payload in ((runtime_infer, infer_config), (runtime_eval, eval_config)):
    partial = path.with_suffix(path.suffix + ".partial")
    with partial.open("wb") as handle:
        tomli_w.dump(payload, handle)
    partial.replace(path)

print(runtime_infer.resolve())
print(runtime_eval.resolve())
print(eval_config["eval"]["max_concurrent_prompts"])
print(eval_config["eval"].get("prompt_batch_size", ""))
PY
)
INFER_CONFIG=${RUNTIME_FIELDS[0]}
RUNTIME_CONFIG=${RUNTIME_FIELDS[1]}
MAX_CONCURRENT=${RUNTIME_FIELDS[2]}
PROMPT_BATCH_SIZE=${RUNTIME_FIELDS[3]}

uv run user/tianhaowu/rsci/snapshot_configs.py "$RUNTIME_CONFIG"
mapfile -t INFER_HOSTS < <(scontrol show hostnames "$SLURM_JOB_NODELIST")
if [ "${#INFER_HOSTS[@]}" -ne "$NODE_COUNT" ]; then
  echo "expected $NODE_COUNT inference hosts, found ${#INFER_HOSTS[@]}" >&2
  exit 1
fi

export RSCI_INFER_CONFIG="$INFER_CONFIG"
export RSCI_OUTPUT_DIR="$OUTPUT_DIR"
srun \
  --nodes="$NODE_COUNT" \
  --ntasks="$NODE_COUNT" \
  --ntasks-per-node=1 \
  --gres=gpu:8 \
  --cpus-per-task=60 \
  --kill-on-bad-exit=1 \
  bash -c '
    set -euo pipefail
    cd /storage/home/tianhaowu/prime-rl
    export HF_HUB_OFFLINE=1
    export PYTHONDONTWRITEBYTECODE=1
    export VLLM_CACHE_ROOT="${SLURM_TMPDIR:-/tmp}/rsci-vllm-${SLURM_JOB_ID}-${SLURM_PROCID}"
    mkdir -p "$VLLM_CACHE_ROOT"
    unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
    uv run --no-sync inference @ "$RSCI_INFER_CONFIG" >"$RSCI_OUTPUT_DIR/server_node_${SLURM_PROCID}.log" 2>&1
  ' &
SERVER_STEP_PID=$!
ROUTER_PID=""
cleanup() {
  if [ -n "$ROUTER_PID" ]; then
    kill -TERM "$ROUTER_PID" 2>/dev/null || true
    wait "$ROUTER_PID" 2>/dev/null || true
  fi
  kill -TERM "$SERVER_STEP_PID" 2>/dev/null || true
  wait "$SERVER_STEP_PID" 2>/dev/null || true
}
trap cleanup EXIT

WORKER_URLS=()
for host in "${INFER_HOSTS[@]}"; do
  WORKER_URLS+=("http://${host}:8100")
done
for attempt in $(seq 1 180); do
  ready=0
  for worker_url in "${WORKER_URLS[@]}"; do
    status=$(curl -sS -o /dev/null --max-time 5 -w '%{http_code}' "${worker_url}/health" 2>/dev/null || true)
    if [ "$status" = 200 ]; then
      ready=$((ready + 1))
    fi
  done
  if [ "$ready" -eq "$NODE_COUNT" ]; then
    echo "all $NODE_COUNT inference replicas ready after $((attempt * 5)) seconds"
    break
  fi
  if ! kill -0 "$SERVER_STEP_PID" 2>/dev/null; then
    echo "multi-node inference step exited before all replicas became ready" >&2
    tail -n 100 "$OUTPUT_DIR"/server_node_*.log >&2
    exit 1
  fi
  if [ "$attempt" = 180 ]; then
    echo "only $ready/$NODE_COUNT inference replicas became ready within 15 minutes" >&2
    exit 1
  fi
  sleep 5
done

uv run --no-sync vllm-router \
  --policy round_robin \
  --host 127.0.0.1 \
  --port 8000 \
  --worker-urls "${WORKER_URLS[@]}" \
  --worker-startup-timeout-secs 60 \
  --request-id-headers x-session-id \
  --log-level info \
  >"$OUTPUT_DIR/server.log" 2>&1 &
ROUTER_PID=$!
for attempt in $(seq 1 60); do
  status=$(curl -sS -o /dev/null --max-time 5 -w '%{http_code}' "http://127.0.0.1:8000/v1/models" 2>/dev/null || true)
  if [ "$status" = 200 ]; then
    echo "router ready with $NODE_COUNT replicas; max_concurrent_prompts=$MAX_CONCURRENT prompt_batch_size=$PROMPT_BATCH_SIZE"
    break
  fi
  if ! kill -0 "$ROUTER_PID" 2>/dev/null; then
    echo "inference router exited before becoming ready" >&2
    tail -n 200 "$OUTPUT_DIR/server.log" >&2
    exit 1
  fi
  if [ "$attempt" = 60 ]; then
    echo "inference router was not ready within 5 minutes" >&2
    exit 1
  fi
  sleep 5
done

uv run "$EVALUATOR" "$RUNTIME_CONFIG"
