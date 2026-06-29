#!/bin/bash
# Eval 17k step-35 checkpoint: heldout-200 (1x) + tb-pass80 (5x) with native_tools
set -uo pipefail
cd "$HOME/prime-rl"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
export OPENAI_API_KEY=dummy-key
export VACLI_LEASE_RETRIES=10 VACLI_MAX_PULL_RETRIES=12
export PYTHONPATH="$HOME/prime-rl/environments/vmvm_tb${PYTHONPATH:+:$PYTHONPATH}"
CFG=user/tianhaowu/fair-sc/configs/eval_17k_step35_infer.toml
MODEL=/checkpoint/ram/tianhaowu/tb_rl_17k_256k/weights/step_35
OUTDIR=/checkpoint/ram/tianhaowu/eval_17k_step35
ROUTER_PORT=8000
mkdir -p "$OUTDIR"

echo "=== submit inference deployment ==="
SUB=$(uv run --no-sync inference @ "$CFG" --model.tool-call-parser qwen3_xml --output-dir "$OUTDIR/inference" 2>&1); echo "$SUB"
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

echo "=== wait for router health ==="
READY=0
for i in $(seq 1 240); do
  if curl -sf "${ROUTER}/models" >/dev/null 2>&1; then READY=1; echo "ROUTER READY ~$((i*10))s"; break; fi
  if [ -z "$(squeue -j "$JOBID" -h -o '%T' 2>/dev/null)" ]; then echo "deployment died"; exit 1; fi
  sleep 10
done
[ "$READY" = 1 ] || { echo "ROUTER NEVER READY"; exit 1; }

echo "=== vf-eval: heldout-200 (1x) ==="
uv run --no-sync vf-eval vmvm-tb \
  -m "$MODEL" \
  --api-base-url "$ROUTER" --api-key-var OPENAI_API_KEY \
  --api-client-type openai_chat_completions \
  --header-from-state "X-Session-ID: trajectory_id" \
  -n 200 --rollouts-per-example 1 --max-concurrent 128 \
  --sampling-args '{"max_tokens":256000,"temperature":1.0,"top_p":0.95,"top_k":20}' \
  --env-args '{"dataset_path":"/checkpoint/ram/tianhaowu/datasets/terminal_bench/v2_heldout_200.jsonl","native_tools":true,"max_rollout_s":7200,"max_turns":300,"command_timeout":300,"test_timeout":900,"session_timeout":3600,"lease_ttl":"11000s","image_source":"task_toml"}' \
  --state-columns turn_timings,tb_outcome,tb_error_class,tb_error_detail,infra_events,tb_test_output,tb_message,tb_exit_code,tb_report \
  --output-dir "$OUTDIR/heldout-200" \
  --save-results --disable-tui --env-dir-path environments
echo "=== heldout-200 exit: $? ==="

echo "=== vf-eval: tb-pass80 (5x) ==="
uv run --no-sync vf-eval vmvm-tb \
  -m "$MODEL" \
  --api-base-url "$ROUTER" --api-key-var OPENAI_API_KEY \
  --api-client-type openai_chat_completions \
  -n 80 --rollouts-per-example 5 --max-concurrent 128 \
  --sampling-args '{"max_tokens":256000,"temperature":1.0,"top_p":0.95,"top_k":20}' \
  --env-args '{"dataset_path":"/checkpoint/ram/tianhaowu/datasets/terminal_bench/v2_harbor_pass80.jsonl","native_tools":true,"max_rollout_s":7200,"max_turns":300,"command_timeout":300,"test_timeout":900,"session_timeout":3600,"lease_ttl":"11000s","image_source":"vmvm_registry"}' \
  --state-columns turn_timings,tb_outcome,tb_error_class,tb_error_detail,infra_events,tb_test_output,tb_message,tb_exit_code,tb_report \
  --output-dir "$OUTDIR/tb-pass80" \
  --save-results --disable-tui --env-dir-path environments
echo "=== tb-pass80 exit: $? ==="
