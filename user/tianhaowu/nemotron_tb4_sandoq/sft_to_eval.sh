#!/bin/bash
# Deploy and evaluate SFT checkpoints as the run writes them. For each step (comma-separated) it waits
# for weights/step_N/STABLE, or, once the job has ended, converts a DCP checkpoint for that step;
# then deploys <deployment>-sN and submits the TB4 eval <name>-sN. Steps proceed independently, so a
# deployment stuck in the queue does not hold back later checkpoints. A deployment that already
# exists (e.g. after restarting this script) is reused instead of redeployed.
# Run in the background on the login node, e.g.
#   MAX_CONTEXT=524288 nohup ./sft_to_eval.sh 1663400 .../outputs/<run> 61,122,183,244,305 \
#       tianhaowu-nemotron-targeted-v2-512k eval/tasks/targeted22.tasks.txt targetedv2-512k-targeted22 4 \
#       > logs/sft_to_eval_targeted_v2.log 2>&1 &
# MAX_CONTEXT (default 262144) is passed to the deployment and the eval context limits.
# WATCH_TIMEOUT (default 86400 s) bounds the wait for each endpoint to start serving.
set -euo pipefail
JOB=${1:?SFT slurm job id}
RUN=${2:?SFT run output dir}
STEPS=${3:?step or comma-separated steps}
DEPLOYMENT=${4:?deployment id prefix}
TASKS=${5:?task list}
NAME=${6:?eval run name prefix}
ROLLOUTS=${7:-4}
HERE=$(cd "$(dirname "$0")" && pwd)
TASKS=$(cd "$HERE" && realpath -e "$TASKS")
SERVE=${SERVE_API_V2:-/storage/home/tianhaowu/ram_common-nemotron/vllm_tools/serve_api_v2}
DEPLOYMENTS=/checkpoint/ram/shared/vllm_deployments_v2
export WATCH_TIMEOUT=${WATCH_TIMEOUT:-86400}
log() { echo "$(date -u +%FT%TZ) $*"; }
job_running() { squeue -h -j "$JOB" 2>/dev/null | grep -q .; }

wait_for_weights() {
    local step=$1 weights="$RUN/weights/step_$1"
    while [[ ! -f "$weights/STABLE" ]] && job_running; do sleep 60; done
    [[ -f "$weights/STABLE" ]] && return 0
    log "[s$step] SFT job $JOB ended ($(sacct -n -X -j "$JOB" -o State | awk '{print $1}')) without $weights"
    [[ -f "$RUN/checkpoints/step_$step/trainer/.metadata" ]] || { log "[s$step] no checkpoint"; return 1; }
    log "[s$step] converting DCP checkpoint"
    sbatch --wait --parsable "$HERE/sft/convert_checkpoint.sh" "$RUN" "$step"
    [[ -f "$weights/STABLE" ]] || { log "[s$step] conversion did not produce $weights"; return 1; }
}

serving() {
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
        "$SERVE/serve.sh" status "$1" 2>/dev/null | head -1 | grep -q serving
}

run_step() {
    local step=$1 id="$DEPLOYMENT-s$1" weights="$RUN/weights/step_$1"
    log "[s$step] waiting for weights"
    wait_for_weights "$step" || return 1
    python3 - "$weights" <<'EOF'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
index = json.loads((root / "model.safetensors.index.json").read_text())
missing = sorted({f for f in index["weight_map"].values() if not (root / f).is_file()})
if missing:
    raise SystemExit(f"missing shards: {missing[:3]}")
print(f"weights ok: {len(index['weight_map'])} tensors, {index['metadata']['total_size'] / 1e9:.1f} GB")
EOF
    local coord_job
    coord_job=$(awk '{print $1}' "$DEPLOYMENTS/$id/coordinator.jobid" 2>/dev/null || true)
    if [[ -n "$coord_job" ]] && squeue -h -j "$coord_job" 2>/dev/null | grep -q .; then
        log "[s$step] reusing existing deployment $id (coordinator $coord_job)"
        local waited=0
        until serving "$id"; do
            sleep 60
            waited=$((waited + 60))
            ((waited < WATCH_TIMEOUT)) || { log "[s$step] $id not serving after ${waited}s"; return 1; }
        done
    else
        log "[s$step] deploying $id"
        MAX_CONTEXT=${MAX_CONTEXT:-262144} "$HERE/serve/deploy.sh" "$id" "$weights" 24h
    fi
    log "[s$step] submitting eval $NAME-s$step ($ROLLOUTS rollouts per task)"
    local eval_job
    eval_job=$(NEMOTRON_TB4_MAX_CONTEXT=${MAX_CONTEXT:-262144} "$HERE/eval/run_eval.sh" "$id" "$TASKS" "$NAME-s$step" "$ROLLOUTS")
    log "[s$step] eval job $eval_job"
}

pids=()
for step in ${STEPS//,/ }; do
    run_step "$step" &
    pids+=($!)
done
status=0
for pid in "${pids[@]}"; do wait "$pid" || status=1; done
log "all steps done (status $status)"
exit $status
