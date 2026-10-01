#!/bin/bash
# Deploy and evaluate SFT checkpoints as the run writes them. For each step (comma-separated) it waits
# for weights/step_N/STABLE, or, once the job has ended, converts a DCP checkpoint for that step;
# then deploys <deployment>-sN and submits the TB4 eval <name>-sN.
# Run in the background on the login node, e.g.
#   MAX_CONTEXT=524288 nohup ./sft_to_eval.sh 1663400 .../outputs/<run> 61,122,183,244,305 \
#       tianhaowu-nemotron-targeted-v2-512k eval/tasks/targeted22.tasks.txt targetedv2-512k-targeted22 4 \
#       > logs/sft_to_eval_targeted_v2.log 2>&1 &
# MAX_CONTEXT (default 262144) is passed to the deployment and the eval context limits.
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
log() { echo "$(date -u +%FT%TZ) $*"; }
job_running() { squeue -h -j "$JOB" 2>/dev/null | grep -q .; }

wait_for_weights() {
    local step=$1 weights="$RUN/weights/step_$1"
    while [[ ! -f "$weights/STABLE" ]] && job_running; do sleep 60; done
    [[ -f "$weights/STABLE" ]] && return 0
    log "SFT job $JOB ended ($(sacct -n -X -j "$JOB" -o State | awk '{print $1}')) without $weights"
    [[ -f "$RUN/checkpoints/step_$step/trainer/.metadata" ]] || { log "no checkpoint for step $step"; return 1; }
    log "converting DCP checkpoint step $step"
    sbatch --wait --parsable "$HERE/sft/convert_checkpoint.sh" "$RUN" "$step"
    [[ -f "$weights/STABLE" ]] || { log "conversion did not produce $weights"; return 1; }
}

for step in ${STEPS//,/ }; do
    log "waiting for step $step"
    wait_for_weights "$step" || continue
    weights="$RUN/weights/step_$step"
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
    log "deploying $DEPLOYMENT-s$step"
    MAX_CONTEXT=${MAX_CONTEXT:-262144} "$HERE/serve/deploy.sh" "$DEPLOYMENT-s$step" "$weights" 24h
    log "submitting eval $NAME-s$step ($ROLLOUTS rollouts per task)"
    eval_job=$(NEMOTRON_TB4_MAX_CONTEXT=${MAX_CONTEXT:-262144} "$HERE/eval/run_eval.sh" "$DEPLOYMENT-s$step" "$TASKS" "$NAME-s$step" "$ROLLOUTS")
    log "eval job $eval_job for step $step"
done
