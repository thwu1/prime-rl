#!/bin/bash
# Terminal-Bench 2.0 eval on Qwen3.5 using prime-rl NATIVE multi-node on H100 (8 replicas) + 5x80 eval.
# inference (5 nodes = 5 tp=8 replicas behind one vllm-router) and the 5x80 task eval
# (rollouts-per-example=5) load-balanced across all replicas through the router.
#
# JUST RUN (in the devserver tmux):  bash run_tb_eval_multinode.sh
set -uo pipefail
cd "$HOME/prime-rl"
export OPENAI_API_KEY=dummy-key
export VACLI_LEASE_RETRIES=10 VACLI_MAX_PULL_RETRIES=12
# the multi-node inference deployment runs `uv sync` on the shared .venv, which
# prunes the editable vmvm_tb install -> make the env importable via PYTHONPATH
# (immune to uv sync; inherited by the vf-eval env-server subprocess).
export PYTHONPATH="$HOME/prime-rl/environments/vmvm_tb${PYTHONPATH:+:$PYTHONPATH}"
CFG=user/tianhaowu/fair-sc/configs/qwen35_infer_multinode_h100.toml
DATASET=/checkpoint/ram/tianhaowu/datasets/terminal_bench/v2_harbor_pass80.jsonl
OUTDIR=/checkpoint/ram/tianhaowu/vmvm_tb_multinode_h100
ROUTER_PORT=8000
mkdir -p "$OUTDIR"

echo "=== submit native multi-node inference deployment ==="
SUB=$(uv run --no-sync inference @ "$CFG" 2>&1); echo "$SUB"
JOBID=$(echo "$SUB" | grep -oE 'Submitted batch job [0-9]+' | grep -oE '[0-9]+$')
[ -n "$JOBID" ] || { echo "FAILED to submit deployment"; exit 1; }
echo "deployment job: $JOBID"
trap 'echo "tearing down deployment $JOBID"; scancel "$JOBID" 2>/dev/null || true' EXIT

echo "=== wait for deployment RUNNING ==="
for i in $(seq 1 120); do
  ST=$(squeue -j "$JOBID" -h -o '%T' 2>/dev/null)
  [ "$ST" = "RUNNING" ] && break
  echo "  state=$ST ($((i*10))s)"; sleep 10
done
NODE0=$(scontrol show hostnames "$(squeue -j "$JOBID" -h -o '%N')" 2>/dev/null | head -1)
[ -n "$NODE0" ] || { echo "no node0"; exit 1; }
ROUTER="http://${NODE0}:${ROUTER_PORT}/v1"
echo "router endpoint: $ROUTER"

echo "=== wait for router health (replicas boot + register) ==="
READY=0
for i in $(seq 1 240); do
  if curl -sf "${ROUTER}/models" >/dev/null 2>&1; then READY=1; echo "ROUTER READY ~$((i*10))s"; break; fi
  if [ -z "$(squeue -j "$JOBID" -h -o '%T' 2>/dev/null)" ]; then echo "deployment died"; exit 1; fi
  sleep 10
done
[ "$READY" = 1 ] || { echo "ROUTER NEVER READY"; exit 1; }

echo "=== vf-eval: 80 tasks x 5 rollouts, load-balanced across 5 replicas via router ==="
uv run --no-sync vf-eval vmvm-tb \
  -m /checkpoint/ram/tianhaowu/Qwen3.5-35B-A3B \
  --api-base-url "$ROUTER" --api-key-var OPENAI_API_KEY \
  --api-client-type openai_chat_completions \
  -n 80 --rollouts-per-example 5 --max-concurrent 128 \
  --sampling-args '{"max_tokens":80000,"temperature":1.0,"top_p":0.95,"top_k":20}' \
  --env-args "{\"dataset_path\":\"$DATASET\",\"native_tools\":true,\"max_turns\":500,\"command_timeout\":300,\"test_timeout\":900,\"session_timeout\":10800,\"lease_ttl\":\"11000s\"}" \
  --state-columns turn_timings,tb_outcome,tb_error_class,tb_error_detail,infra_events,tb_test_output,tb_message,tb_exit_code,tb_report \
  --output-dir "$OUTDIR" \
  --save-results --disable-tui --env-dir-path environments
echo "=== vf-eval exit: $? ==="
# teardown via trap
