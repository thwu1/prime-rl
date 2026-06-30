#!/bin/bash
#SBATCH --job-name=tmax-run
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --output=/checkpoint/ram/tianhaowu/tmax_run_logs/run_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/tmax_run_logs/run_%j.log

# Smoke run: 10 converted TMax->harbor tasks via vf-eval vmvm-tb against an existing
# Qwen3.5-35B inference router. Runs on a cpu node (vf-eval leases task VMs via vacli,
# which can't run from the sandbox pod). ROUTER/DATASET overridable via --export.
set -u
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
cd "$HOME/prime-rl"
export OPENAI_API_KEY=dummy-key
export VACLI_LEASE_RETRIES=10 VACLI_MAX_PULL_RETRIES=12
export PYTHONPATH="$HOME/prime-rl/environments/vmvm_tb${PYTHONPATH:+:$PYTHONPATH}"

ROUTER="${ROUTER:-http://h200-041-027:8000/v1}"
MODEL="${MODEL:-/checkpoint/ram/tianhaowu/Qwen3.5-35B-A3B}"
DATASET="${DATASET:-/checkpoint/ram/tianhaowu/tmax_smoke10.jsonl}"
OUTDIR="${OUTDIR:-/checkpoint/ram/tianhaowu/tmax_smoke_run}"
mkdir -p "$OUTDIR"
echo "=== tmax smoke run: $(wc -l < "$DATASET") tasks @ $ROUTER -> $OUTDIR ==="

uv run --no-sync vf-eval vmvm-tb \
  -m "$MODEL" \
  --api-base-url "$ROUTER" --api-key-var OPENAI_API_KEY \
  --api-client-type openai_chat_completions \
  --header-from-state "X-Session-ID: trajectory_id" \
  -n 10 --rollouts-per-example 2 --max-concurrent 3 \
  --sampling-args '{"max_tokens":40000,"temperature":1.0,"top_p":0.95,"top_k":20}' \
  --env-args "{\"dataset_path\":\"$DATASET\",\"image_source\":\"vmvm_registry\",\"max_turns\":50,\"command_timeout\":120,\"test_timeout\":600,\"session_timeout\":1800,\"max_rollout_s\":2400,\"lease_ttl\":\"3600s\"}" \
  --state-columns turn_timings,tb_outcome,tb_error_class,tb_error_detail,tb_test_output,tb_message,tb_exit_code,tb_report \
  --output-dir "$OUTDIR" \
  --save-results --disable-tui --env-dir-path environments
echo "=== vf-eval exit: $? ==="
