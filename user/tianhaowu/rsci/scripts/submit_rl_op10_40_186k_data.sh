#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=/storage/home/tianhaowu/prime-rl
OUTPUT_DIR=${1:-/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op10-40-balanced-186k}
ARRAY_JOB_NAME=rsci-data-op10-45-186k
FINALIZE_JOB_NAME=rsci-data-finalize-op10-45-186k

cd "$REPO_ROOT"
mkdir -p "$OUTPUT_DIR"
exec 9>"$OUTPUT_DIR/.submission.lock"
flock 9

if uv run --no-sync python user/tianhaowu/rsci/prepare_rl_op10_40_dataset_186k.py \
  check --output-dir "$OUTPUT_DIR" >/dev/null 2>&1; then
  echo "dataset is already complete: $OUTPUT_DIR"
  exit 0
fi

ACTIVE_JOBS=$(
  {
    squeue --noheader --name "$ARRAY_JOB_NAME" --format='%A %T %R'
    squeue --noheader --name "$FINALIZE_JOB_NAME" --format='%A %T %R'
  } | sed '/^[[:space:]]*$/d'
)
if [[ -n "$ACTIVE_JOBS" ]]; then
  echo "dataset preparation is already active:"
  echo "$ACTIVE_JOBS"
  exit 0
fi

ARRAY_SUBMISSION=$(env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch --parsable user/tianhaowu/rsci/scripts/prepare_rl_op10_40_186k_array.sbatch "$OUTPUT_DIR")
ARRAY_JOB_ID=${ARRAY_SUBMISSION%%;*}
FINALIZE_SUBMISSION=$(env -u SBATCH_OUTPUT -u SBATCH_ERROR \
  sbatch --parsable --dependency="afterok:$ARRAY_JOB_ID" \
  user/tianhaowu/rsci/scripts/finalize_rl_op10_40_186k.sbatch "$OUTPUT_DIR")
FINALIZE_JOB_ID=${FINALIZE_SUBMISSION%%;*}

echo "submitted 186k shard array: $ARRAY_JOB_ID"
echo "submitted dependent 186k finalizer: $FINALIZE_JOB_ID"
