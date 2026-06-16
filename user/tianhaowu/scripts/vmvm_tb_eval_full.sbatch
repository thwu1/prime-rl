#!/bin/bash
#SBATCH --job-name=vmvm-tb-eval-full
#SBATCH --account=ram
#SBATCH --qos=h200_ram_high
#SBATCH --nodes=1
#SBATCH --gpus-per-node=8
#SBATCH --cpus-per-task=96
#SBATCH --time=08:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/vmvm_tb_evalfull_%j.log

set -x
cd "$HOME/prime-rl"
export OPENAI_API_KEY=dummy-key
N=${VMVM_N:-86}
CONC=${VMVM_CONC:-12}

uv run --no-sync inference @ /checkpoint/ram/tianhaowu/qwen35_infer_fast.toml > /checkpoint/ram/tianhaowu/vmvm_tb_infer_full.log 2>&1 &
SERVER_PID=$!
READY=0
for i in $(seq 1 120); do
  if curl -sf http://localhost:8000/v1/models >/dev/null 2>&1; then READY=1; echo "SERVER READY after ~$((i*10))s"; break; fi
  if ! kill -0 $SERVER_PID 2>/dev/null; then echo "SERVER DIED"; tail -40 /checkpoint/ram/tianhaowu/vmvm_tb_infer_full.log; exit 1; fi
  sleep 10
done
[ "$READY" = 1 ] || { echo "SERVER NEVER READY"; kill $SERVER_PID; exit 1; }

echo "=== vf-eval: N=$N concurrency=$CONC ==="
uv run --no-sync vf-eval vmvm-tb \
  -m /checkpoint/ram/tianhaowu/Qwen3.5-35B-A3B \
  --api-base-url http://localhost:8000/v1 --api-key-var OPENAI_API_KEY \
  --api-client-type openai_chat_completions \
  -n "$N" --rollouts-per-example 1 --max-concurrent "$CONC" \
  --max-tokens 8192 --temperature 0.7 \
  --state-columns turn_timings \
  --save-results --disable-tui --env-dir-path environments
echo "=== vf-eval exit: $? ==="
kill $SERVER_PID 2>/dev/null || true
sleep 5
