#!/bin/bash
#SBATCH --job-name=vmvm-tb-eval1
#SBATCH --account=ram
#SBATCH --qos=h200_ram_high
#SBATCH --nodes=1
#SBATCH --gpus-per-node=8
#SBATCH --cpus-per-task=64
#SBATCH --time=02:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/vmvm_tb_eval1_%j.log

set -x
cd "$HOME/prime-rl"
export OPENAI_API_KEY=dummy-key

# 1) serve Qwen3.5 (vLLM, cache warm now) in background
uv run --no-sync inference @ /checkpoint/ram/tianhaowu/qwen35_infer.toml > /checkpoint/ram/tianhaowu/vmvm_tb_infer.log 2>&1 &
SERVER_PID=$!

# 2) wait for readiness (cache warm -> should be a few min)
READY=0
for i in $(seq 1 90); do
  if curl -sf http://localhost:8000/v1/models >/dev/null 2>&1; then READY=1; echo "SERVER READY after ~$((i*10))s"; break; fi
  if ! kill -0 $SERVER_PID 2>/dev/null; then echo "SERVER DIED"; tail -40 /checkpoint/ram/tianhaowu/vmvm_tb_infer.log; exit 1; fi
  sleep 10
done
[ "$READY" = 1 ] || { echo "SERVER NEVER READY"; tail -40 /checkpoint/ram/tianhaowu/vmvm_tb_infer.log; kill $SERVER_PID; exit 1; }

# 3) run verifiers eval of vmvm-tb on 1 task against the served model
echo "=== STARTING vf-eval (1 task) ==="
uv run --no-sync vf-eval vmvm-tb \
  -m /checkpoint/ram/tianhaowu/Qwen3.5-35B-A3B \
  --api-base-url http://localhost:8000/v1 \
  --api-key-var OPENAI_API_KEY \
  --api-client-type openai_chat_completions \
  -n 1 --rollouts-per-example 1 --max-concurrent 1 \
  --max-tokens 8192 --temperature 0.7 \
  --save-results --disable-tui --env-dir-path environments
EVAL_RC=$?
echo "=== vf-eval exit code: $EVAL_RC ==="

kill $SERVER_PID 2>/dev/null || true
sleep 5
