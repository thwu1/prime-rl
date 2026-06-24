#!/bin/bash
# tb_v2 (17k) eval on Qwen3.5 via prime-rl multi-node inference. Uses the
# task.toml docker.io images (image_source=task_toml). DATASET/OUTDIR/ROLLOUTS
# overridable via env (sbatch --export) for smoke vs full.
set -uo pipefail
cd "$HOME/prime-rl"
export OPENAI_API_KEY=dummy-key
export VACLI_LEASE_RETRIES=10 VACLI_MAX_PULL_RETRIES=12
export PYTHONPATH="$HOME/prime-rl/environments/vmvm_tb${PYTHONPATH:+:$PYTHONPATH}"
# Clear any proxy the cpu node profile may inject so curl/vf-eval/vacli reach
# the in-cluster h200 router + VMs directly (internal IPs are not proxy-routable).
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
CFG=user/tianhaowu/fair-sc/configs/qwen35_infer_multinode_120h.toml
DATASET=${DATASET:-/checkpoint/ram/tianhaowu/datasets/terminal_bench/v2_train_full_tr.jsonl}
OUTDIR=${OUTDIR:-/checkpoint/ram/tianhaowu/vmvm_tb_v2_17k_pass4_base}
ROLLOUTS=${ROLLOUTS:-4}
ROUTER_PORT=8000
mkdir -p "$OUTDIR"
N=$(wc -l < "$DATASET")
echo "=== tb_v2 eval: $N tasks x $ROLLOUTS rollouts -> $OUTDIR (dataset=$DATASET) ==="

SUB=$(uv run --no-sync inference @ "$CFG" 2>&1); echo "$SUB"
JOBID=$(echo "$SUB" | grep -oE 'Submitted batch job [0-9]+' | grep -oE '[0-9]+$')
[ -n "$JOBID" ] || { echo "FAILED to submit deployment"; exit 1; }
echo "deployment job: $JOBID"
trap 'echo "tearing down deployment $JOBID"; scancel "$JOBID" 2>/dev/null || true' EXIT

for i in $(seq 1 180); do
  ST=$(squeue -j "$JOBID" -h -o '%T' 2>/dev/null)
  [ "$ST" = "RUNNING" ] && break
  echo "  state=$ST ($((i*10))s)"; sleep 10
done
NODE0=$(scontrol show hostnames "$(squeue -j "$JOBID" -h -o '%N')" 2>/dev/null | head -1)
[ -n "$NODE0" ] || { echo "no node0"; exit 1; }
ROUTER="http://${NODE0}:${ROUTER_PORT}/v1"
echo "router endpoint: $ROUTER"

READY=0
BACKEND="http://${NODE0}:8100"
for i in $(seq 1 240); do
  CODE=$(curl -s -o /dev/null -m 10 -w "%{http_code}" "${ROUTER}/models" 2>/dev/null)
  BCODE=$(curl -s -o /dev/null -m 10 -w "%{http_code}" "${BACKEND}/v1/models" 2>/dev/null)
  echo "  readiness poll $i ($((i*10))s): router ${ROUTER}/models -> ${CODE:-conn_fail} | backend ${BACKEND}/v1/models -> ${BCODE:-conn_fail}"
  if [ "$CODE" = "200" ]; then READY=1; echo "ROUTER READY ~$((i*10))s (router 200)"; break; fi
  if [ -z "$(squeue -j "$JOBID" -h -o '%T' 2>/dev/null)" ]; then echo "deployment died"; exit 1; fi
  sleep 10
done
[ "$READY" = 1 ] || { echo "ROUTER NEVER READY (last: router=${CODE:-conn_fail} backend=${BCODE:-conn_fail})"; exit 1; }

uv run --no-sync vf-eval vmvm-tb \
  -m /checkpoint/ram/tianhaowu/Qwen3.5-35B-A3B \
  --api-base-url "$ROUTER" --api-key-var OPENAI_API_KEY \
  --api-client-type openai_chat_completions \
  -n "$N" --rollouts-per-example "$ROLLOUTS" --max-concurrent 512 \
  --sampling-args '{"max_tokens":80000,"temperature":1.0,"top_p":0.95,"top_k":20}' \
  --env-args "{\"dataset_path\":\"$DATASET\",\"image_source\":\"task_toml\",\"max_turns\":300,\"command_timeout\":300,\"test_timeout\":900,\"session_timeout\":3600,\"max_rollout_s\":7200,\"lease_ttl\":\"11000s\"}" \
  --state-columns turn_timings,tb_outcome,tb_error_class,tb_error_detail,infra_events,tb_test_output,tb_message,tb_exit_code,tb_report \
  --output-dir "$OUTDIR" \
  --save-results --disable-tui --env-dir-path environments
echo "=== vf-eval exit: $? ==="
