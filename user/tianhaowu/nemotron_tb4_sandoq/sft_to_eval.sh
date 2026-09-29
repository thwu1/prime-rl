#!/bin/bash
# After an SFT job ends: convert its final DCP checkpoint, deploy it, and submit the TB4 eval.
# Run in the background on the login node, e.g.
#   nohup ./sft_to_eval.sh 1623745 .../outputs/tb4-23-overfit-262k-cp2-8node-lr1e5-10ep-r2 109 \
#       tianhaowu-nemotron-tb4-sft-262k eval/tasks/trained19.tasks.txt sft262k-trained19 4 \
#       > logs/sft_to_eval_262k.log 2>&1 &
set -euo pipefail
JOB=${1:?SFT slurm job id}
RUN=${2:?SFT run output dir}
STEP=${3:?final step}
DEPLOYMENT=${4:?deployment id}
TASKS=${5:?task list}
NAME=${6:?eval run name}
ROLLOUTS=${7:-4}
HERE=$(cd "$(dirname "$0")" && pwd)
log() { echo "$(date -u +%FT%TZ) $*"; }

log "waiting for SFT job $JOB"
while squeue -h -j "$JOB" 2>/dev/null | grep -q .; do sleep 60; done
state=$(sacct -n -X -j "$JOB" -o State | awk '{print $1}')
log "SFT job $JOB finished: $state"

weights="$RUN/weights/step_$STEP"
if [[ ! -f "$weights/STABLE" ]]; then
    [[ -f "$RUN/checkpoints/step_$STEP/trainer/.metadata" ]] \
        || { log "no final checkpoint in $RUN (state $state)"; exit 1; }
    log "converting DCP checkpoint step $STEP"
    sbatch --wait --parsable "$HERE/sft/convert_checkpoint.sh" "$RUN" "$STEP"
    [[ -f "$weights/STABLE" ]] || { log "conversion did not produce $weights"; exit 1; }
fi
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

log "deploying $DEPLOYMENT"
"$HERE/serve/deploy.sh" "$DEPLOYMENT" "$weights" 24h
log "submitting eval $NAME ($ROLLOUTS rollouts per task)"
eval_job=$("$HERE/eval/run_eval.sh" "$DEPLOYMENT" "$(cd "$HERE" && realpath -e "$TASKS")" "$NAME" "$ROLLOUTS")
log "eval job $eval_job"
