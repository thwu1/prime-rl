#!/usr/bin/env bash
#SBATCH --job-name=rsci-frozen-eval
#SBATCH --qos=h100_ram_high
#SBATCH --account=ram
#SBATCH --partition=h100
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=04:00:00

set -euo pipefail

RUN_DIR=${1:?usage: run_rl_checkpoint_eval_array.sbatch RUN_DIR STEP_MANIFEST}
STEP_MANIFEST=${2:?usage: run_rl_checkpoint_eval_array.sbatch RUN_DIR STEP_MANIFEST}
TASK_ID=${SLURM_ARRAY_TASK_ID:?SLURM_ARRAY_TASK_ID is required}
ARRAY_JOB_ID=${SLURM_ARRAY_JOB_ID:-${SLURM_JOB_ID:?SLURM_JOB_ID is required}}

if [[ ! "$TASK_ID" =~ ^[0-9]+$ ]] || [[ ! "$ARRAY_JOB_ID" =~ ^[0-9]+$ ]]; then
  echo "invalid Slurm array identity: job=$ARRAY_JOB_ID task=$TASK_ID" >&2
  exit 2
fi

SOURCE_BOOTSTRAP="$RUN_DIR/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot.sh"
if [[ ! -f "$SOURCE_BOOTSTRAP" ]]; then
  echo "frozen source bootstrap does not exist: $SOURCE_BOOTSTRAP" >&2
  exit 1
fi
source "$SOURCE_BOOTSTRAP" "$RUN_DIR"
REPO_ROOT=$RSCI_SOURCE_SNAPSHOT
cd "$REPO_ROOT"
STEP=$(sed -n "$((TASK_ID + 1))p" "$STEP_MANIFEST")
if [[ ! "$STEP" =~ ^(0|[1-9][0-9]*)$ ]]; then
  echo "invalid or missing step for array task $TASK_ID in $STEP_MANIFEST: $STEP" >&2
  exit 2
fi
if (( STEP != 0 && (STEP < 25 || STEP > 500 || STEP % 25 != 0) )); then
  echo "step is outside the frozen evaluation grid in $STEP_MANIFEST: $STEP" >&2
  exit 2
fi

OUTPUT_DIR="$RUN_DIR/evals/op11-45/step_$STEP"
METRICS_PATH="$OUTPUT_DIR/metrics.json"
if uv run --no-sync user/tianhaowu/rsci/checkpoint_eval_artifacts.py validate "$RUN_DIR" "$STEP"; then
  echo "already complete and valid: $METRICS_PATH"
  exit 0
else
  VALIDATION_STATUS=$?
  if (( VALIDATION_STATUS != 1 )); then
    exit "$VALIDATION_STATUS"
  fi
fi
if [[ -f "$METRICS_PATH" ]]; then
  QUARANTINE_TAG="${ARRAY_JOB_ID}.task${TASK_ID}"
  QUARANTINE_PATH=$(uv run --no-sync user/tianhaowu/rsci/checkpoint_eval_artifacts.py \
    quarantine-invalid "$RUN_DIR" "$STEP" --tag "$QUARANTINE_TAG")
  echo "quarantined invalid completion marker: $QUARANTINE_PATH"
fi

PORT=$((20000 + (ARRAY_JOB_ID * 37 + TASK_ID) % 20000))
EVAL_CONFIG=$(uv run --no-sync user/tianhaowu/rsci/prepare_rl_checkpoint_eval.py \
  "$RUN_DIR" "$STEP" --port "$PORT")
export UV_NO_SYNC=1
export VLLM_CACHE_ROOT="${SLURM_TMPDIR:-/tmp}/rsci-frozen-eval-${ARRAY_JOB_ID}-${TASK_ID}"
exec bash user/tianhaowu/rsci/scripts/run_eval.sh "$EVAL_CONFIG"
