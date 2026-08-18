#!/usr/bin/env bash
#SBATCH --job-name=rsci-vd-gstar-eval
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

EVAL_LAUNCH_MANIFEST=${1:?usage: fixed_clock_sft_gstar_eval_array.sbatch EVAL_LAUNCH_MANIFEST SUBMISSION_PLAN SOURCE_RUN_DIR}
SUBMISSION_PLAN=${2:?usage: fixed_clock_sft_gstar_eval_array.sbatch EVAL_LAUNCH_MANIFEST SUBMISSION_PLAN SOURCE_RUN_DIR}
SOURCE_RUN_DIR=${3:?usage: fixed_clock_sft_gstar_eval_array.sbatch EVAL_LAUNCH_MANIFEST SUBMISSION_PLAN SOURCE_RUN_DIR}
TASK_INDEX=${SLURM_ARRAY_TASK_ID:?SLURM_ARRAY_TASK_ID is required}
ARRAY_JOB_ID=${SLURM_ARRAY_JOB_ID:-${SLURM_JOB_ID:?SLURM_JOB_ID is required}}

if [[ ! "$TASK_INDEX" =~ ^(0|[1-9][0-9]*)$ ]] || [[ ! "$ARRAY_JOB_ID" =~ ^[1-9][0-9]*$ ]]; then
  echo "invalid Slurm array identity: job=$ARRAY_JOB_ID task=$TASK_INDEX" >&2
  exit 2
fi

SOURCE_RUN_DIR=$(realpath "$SOURCE_RUN_DIR")
SOURCE_BOOTSTRAP="$SOURCE_RUN_DIR/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot_eval.sh"
if [[ ! -f "$SOURCE_BOOTSTRAP" ]]; then
  echo "pinned evaluation source bootstrap does not exist: $SOURCE_BOOTSTRAP" >&2
  exit 1
fi
source "$SOURCE_BOOTSTRAP" "$SOURCE_RUN_DIR"
cd "$RSCI_SOURCE_SNAPSHOT"

EVAL_ROOT=$(dirname "$(realpath "$EVAL_LAUNCH_MANIFEST")")
SUBMISSION_RECEIPT="$EVAL_ROOT/submissions/jobs/${ARRAY_JOB_ID}.json"
for _ in {1..120}; do
  [[ -f "$SUBMISSION_RECEIPT" ]] && break
  sleep 1
done
if [[ ! -f "$SUBMISSION_RECEIPT" ]]; then
  echo "immutable Gstar evaluation receipt did not appear: $SUBMISSION_RECEIPT" >&2
  exit 1
fi

EVAL_CONFIG=$(uv run --no-sync python user/tianhaowu/rsci/materialize_fixed_clock_sft_gstar_evals.py prepare-task \
  --eval-launch-manifest "$EVAL_LAUNCH_MANIFEST" \
  --submission-plan "$SUBMISSION_PLAN" \
  --task-index "$TASK_INDEX" \
  --array-job-id "$ARRAY_JOB_ID" \
  --print-config)

export HF_HUB_OFFLINE=1
export UV_NO_SYNC=1
export VLLM_CACHE_ROOT="${SLURM_TMPDIR:-/tmp}/rsci-vd-gstar-eval-${ARRAY_JOB_ID}-${TASK_INDEX}"
exec bash user/tianhaowu/rsci/scripts/run_eval.sh "$EVAL_CONFIG"
