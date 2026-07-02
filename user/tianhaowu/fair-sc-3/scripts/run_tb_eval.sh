#!/bin/bash
# Unified eval runner (analogous to run_tb_rl.sh for training): serve a checkpoint via the
# `inference` entrypoint, then run vf-eval on each [[eval.env]] in the config. Teardown on exit.
#
# Usage: bash run_tb_eval.sh <eval_config.toml>
#   The eval config specifies: infer_config (+ [infer_overrides]) for the deployment, and
#   [eval] (output_dir, max_concurrent, model, sampling) + [[eval.env]] blocks (vf_env, name,
#   rollouts_per_example, dataset_path, env_args). See configs/eval_ckpt175.toml.
set -uo pipefail
cd "$HOME/prime-rl"
# Same env as run_tb_rl.sh (editable envs on PYTHONPATH; CUDA 12.9 toolkit; HF offline).
export PYTHONPATH="$HOME/prime-rl/environments/vmvm_tb:$HOME/prime-rl/environments/vmvm_tb_v1${PYTHONPATH:+:$PYTHONPATH}"
export CUDA_HOME=/checkpoint/ram-h100-2/tianhaowu/envs/cuda129
export PATH="$CUDA_HOME/bin:$PATH"
export HF_HUB_OFFLINE=1
export OPENAI_API_KEY=dummy-key
export VACLI_LEASE_RETRIES=20 VACLI_MAX_PULL_RETRIES=10
# Clear any proxy the cpu-node profile injects so curl/vf-eval/vacli reach the in-cluster
# h200 router + VMs directly (internal IPs are not proxy-routable).
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

[ $# -ge 1 ] || { echo "usage: $0 <eval_config.toml>" >&2; exit 2; }
CFG=$1
ROUTER_PORT=8000; BACKEND_PORT=8100

# --- parse the eval config (python/tomllib -> tab-separated lines) ---
PARSED=$(uv run --no-sync python - "$CFG" <<'PY'
import sys, json, tomllib
c=tomllib.load(open(sys.argv[1],'rb'))
ov=c.get("infer_overrides",{})
args=" ".join(f'--{k} {v}' for k,v in ov.items())
e=c["eval"]
print("INFER_CONFIG\t"+c["infer_config"])
print("INFER_ARGS\t"+args)
print("OUTPUT_DIR\t"+e["output_dir"])
print("MAX_CONCURRENT\t"+str(e.get("max_concurrent",512)))
print("MODEL\t"+e["model"])
print("SAMPLING\t"+e["sampling"])
for env in e["env"]:
    ea=json.loads(env["env_args"]); ea["dataset_path"]=env["dataset_path"]
    print("ENV\t"+"\t".join([env["vf_env"],env["name"],str(env["rollouts_per_example"]),env["dataset_path"],json.dumps(ea)]))
PY
)
[ -n "$PARSED" ] || { echo "failed to parse $CFG"; exit 1; }
get(){ echo "$PARSED" | awk -F'\t' -v k="$1" '$1==k{print substr($0, length(k)+2); exit}'; }
INFER_CONFIG=$(get INFER_CONFIG); INFER_ARGS=$(get INFER_ARGS)
OUTPUT_DIR=$(get OUTPUT_DIR); MAX_CONCURRENT=$(get MAX_CONCURRENT)
MODEL=$(get MODEL); SAMPLING=$(get SAMPLING)
mkdir -p "$OUTPUT_DIR"
echo "=== eval: model=$MODEL -> $OUTPUT_DIR (infer @ $INFER_CONFIG $INFER_ARGS) ==="

# --- submit the inference deployment ---
SUB=$(uv run --no-sync inference @ "$INFER_CONFIG" $INFER_ARGS --output-dir "$OUTPUT_DIR/_deploy" 2>&1); echo "$SUB"
JOBID=$(echo "$SUB" | grep -oE 'Submitted batch job [0-9]+' | grep -oE '[0-9]+$')
[ -n "$JOBID" ] || { echo "FAILED to submit deployment"; exit 1; }
echo "deployment job: $JOBID"
trap 'echo "tearing down deployment $JOBID"; scancel "$JOBID" 2>/dev/null || true' EXIT

for i in $(seq 1 720); do  # up to ~2h to schedule on a busy h200 queue
  ST=$(squeue -j "$JOBID" -h -o '%T' 2>/dev/null)
  [ "$ST" = "RUNNING" ] && break
  [ -z "$ST" ] && { echo 'deployment left queue before RUNNING'; exit 1; }
  echo "  state=$ST ($((i*10))s)"; sleep 10
done
NODE0=$(scontrol show hostnames "$(squeue -j "$JOBID" -h -o '%N')" 2>/dev/null | head -1)
[ -n "$NODE0" ] || { echo "no node0"; exit 1; }
ROUTER="http://${NODE0}:${ROUTER_PORT}/v1"
echo "router endpoint: $ROUTER"

READY=0
for i in $(seq 1 240); do
  CODE=$(curl -s -o /dev/null -m 10 -w "%{http_code}" "${ROUTER}/models" 2>/dev/null)
  echo "  readiness poll $i ($((i*10))s): ${ROUTER}/models -> ${CODE:-conn_fail}"
  [ "$CODE" = "200" ] && { READY=1; echo "ROUTER READY ~$((i*10))s"; break; }
  [ -z "$(squeue -j "$JOBID" -h -o '%T' 2>/dev/null)" ] && { echo "deployment died"; exit 1; }
  sleep 10
done
[ "$READY" = 1 ] || { echo "ROUTER NEVER READY"; exit 1; }

# --- run vf-eval per env ---
RC=0
echo "$PARSED" | awk -F'\t' '$1=="ENV"' | while IFS=$'\t' read -r _ VF_ENV NAME ROLLOUTS DATASET ENV_ARGS; do
  N=$(wc -l < "$DATASET")
  echo "=== vf-eval $VF_ENV / $NAME: $N tasks x $ROLLOUTS -> $OUTPUT_DIR/$NAME ==="
  uv run --no-sync vf-eval "$VF_ENV" \
    -m "$MODEL" \
    --api-base-url "$ROUTER" --api-key-var OPENAI_API_KEY \
    --api-client-type openai_chat_completions \
    --header-from-state "X-Session-ID: trajectory_id" \
    -n "$N" --rollouts-per-example "$ROLLOUTS" --max-concurrent "$MAX_CONCURRENT" \
    --sampling-args "$SAMPLING" \
    --env-args "$ENV_ARGS" \
    --state-columns turn_timings,tb_outcome,tb_error_class,tb_error_detail,infra_events,tb_test_output,tb_message,tb_exit_code,tb_report \
    --output-dir "$OUTPUT_DIR/$NAME" \
    --save-results --disable-tui --env-dir-path environments || RC=1
  echo "=== vf-eval $NAME exit ($RC) ==="
done
echo "=== all evals done ==="
