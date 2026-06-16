#!/bin/bash
# Terminal-Bench 2.0 reference eval — Qwen3.5-35B-A3B on prime-rl + VMVM/vacli.
# Runs each of the 80 tasks 5x (one run per node, 5 nodes in parallel) at the reference
# config: temp=1.0 top_p=0.95 top_k=20 max_tokens=80K, 256K ctx, 3h/task. Reportable
# number = mean pass@1 over the 5 runs (printed by agg_ref_runs.py).
#
# JUST RUN:  bash run_tb_eval_ref_5runs.sh      (it submits itself to SLURM)
#
#SBATCH --job-name=vmvm-tb-ref5
#SBATCH --account=ram
#SBATCH --qos=h200_ram_high
#SBATCH --array=0-4
#SBATCH --nodes=1
#SBATCH --gpus-per-node=8
#SBATCH --cpus-per-task=96
#SBATCH --time=24:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/vmvm_tb_ref5_%A_%a.log

# self-submit if launched from a normal shell (no env vars for the user to set)
if [ -z "${SLURM_JOB_ID:-}" ]; then
  exec sbatch "$0"
fi

set -x
cd "$HOME/prime-rl"
export OPENAI_API_KEY=dummy-key
# high-concurrency (128/node) -> bigger lease herd: raise vacli lease retries + pull retries
export VACLI_LEASE_RETRIES=10
export VACLI_MAX_PULL_RETRIES=12
SEED=${SLURM_ARRAY_TASK_ID:-0}
# Stagger boots: 5 nodes reading the shared ~467MB flashinfer + torch_compile cache
# at once causes slow startup / dropped seeds. Spread boots ~60s apart.
sleep $((SEED * 60))
OUTDIR="/checkpoint/ram/tianhaowu/vmvm_tb_ref_runs/seed${SEED}"
mkdir -p "$OUTDIR"

uv run --no-sync inference @ /checkpoint/ram/tianhaowu/qwen35_infer_fast.toml \
  > "/checkpoint/ram/tianhaowu/vmvm_tb_infer_ref5_${SLURM_ARRAY_JOB_ID}_${SEED}.log" 2>&1 &
SERVER_PID=$!
READY=0
for i in $(seq 1 180); do
  if curl -sf http://localhost:8000/v1/models >/dev/null 2>&1; then READY=1; echo "SEED $SEED READY ~$((i*10))s"; break; fi
  if ! kill -0 $SERVER_PID 2>/dev/null; then echo "SERVER DIED"; tail -40 "/checkpoint/ram/tianhaowu/vmvm_tb_infer_ref5_${SLURM_ARRAY_JOB_ID}_${SEED}.log"; exit 1; fi
  sleep 10
done
[ "$READY" = 1 ] || { echo "SERVER NEVER READY"; kill $SERVER_PID; exit 1; }

uv run --no-sync vf-eval vmvm-tb \
  -m /checkpoint/ram/tianhaowu/Qwen3.5-35B-A3B \
  --api-base-url http://localhost:8000/v1 --api-key-var OPENAI_API_KEY \
  --api-client-type openai_chat_completions \
  -n 80 --rollouts-per-example 1 --max-concurrent 128 \
  --sampling-args '{"max_tokens":80000,"temperature":1.0,"top_p":0.95,"top_k":20}' \
  --env-args '{"dataset_path":"/checkpoint/ram/tianhaowu/datasets/terminal_bench/v2_harbor_pass80.jsonl","max_turns":500,"command_timeout":300,"test_timeout":900,"session_timeout":3600,"lease_ttl":"11000s"}' \
  --state-columns turn_timings,tb_outcome,tb_error_class,tb_error_detail,tb_test_output,tb_message,tb_exit_code,tb_report \
  --output-dir "$OUTDIR" \
  --save-results --disable-tui --env-dir-path environments
echo "=== SEED $SEED exit: $? ==="
kill $SERVER_PID 2>/dev/null || true
sleep 5
