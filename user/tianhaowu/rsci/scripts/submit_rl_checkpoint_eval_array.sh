#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
usage: submit_rl_checkpoint_eval_array.sh [--dependency SLURM_DEPENDENCY] [--max-parallel N] RUN_DIR

Submits one 1-H100 array task for each incomplete frozen evaluation at steps
0, 25, ..., 500. A live prior submission for the same run is returned instead
of duplicated. Example dependency: afterok:12345678.
EOF
}

LIVE_REPO_ROOT=/storage/home/tianhaowu/prime-rl
DEPENDENCY=""
MAX_PARALLEL=8
RUN_DIR=""

while (( $# > 0 )); do
  case "$1" in
    --dependency)
      (( $# >= 2 )) || { usage >&2; exit 2; }
      DEPENDENCY=$2
      shift 2
      ;;
    --max-parallel)
      (( $# >= 2 )) || { usage >&2; exit 2; }
      MAX_PARALLEL=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -n "$RUN_DIR" ]]; then
        echo "only one RUN_DIR may be provided" >&2
        usage >&2
        exit 2
      fi
      RUN_DIR=$1
      shift
      ;;
  esac
done

if [[ -z "$RUN_DIR" ]]; then
  usage >&2
  exit 2
fi
if [[ ! "$MAX_PARALLEL" =~ ^[1-9][0-9]*$ ]]; then
  echo "--max-parallel must be a positive integer, got: $MAX_PARALLEL" >&2
  exit 2
fi

cd "$LIVE_REPO_ROOT"
RUN_DIR=$(realpath "$RUN_DIR")
if [[ ! -f "$RUN_DIR/configs/trainer.toml" ]]; then
  echo "resolved trainer config does not exist: $RUN_DIR/configs/trainer.toml" >&2
  exit 1
fi
SOURCE_BOOTSTRAP="$RUN_DIR/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot.sh"
if [[ ! -f "$SOURCE_BOOTSTRAP" ]]; then
  echo "frozen source bootstrap does not exist: $SOURCE_BOOTSTRAP" >&2
  exit 1
fi
source "$SOURCE_BOOTSTRAP" "$RUN_DIR"
REPO_ROOT=$RSCI_SOURCE_SNAPSHOT
cd "$REPO_ROOT"

BATCH_DIR="$RUN_DIR/evals/op11-45/array"
mkdir -p "$BATCH_DIR"
LOCK_PATH="$BATCH_DIR/submission.lock"
ACTIVE_JOB_PATH="$BATCH_DIR/active_job_id"
exec {LOCK_FD}>"$LOCK_PATH"
flock "$LOCK_FD"

if [[ -f "$ACTIVE_JOB_PATH" ]]; then
  ACTIVE_JOB_ID=$(<"$ACTIVE_JOB_PATH")
  if [[ "$ACTIVE_JOB_ID" =~ ^[0-9]+$ ]]; then
    if ! LIVE_STATE=$(squeue --noheader --jobs "$ACTIVE_JOB_ID" --format='%T' 2>&1); then
      if [[ "$LIVE_STATE" != *"Invalid job id specified"* ]]; then
        echo "squeue failed for prior array $ACTIVE_JOB_ID: $LIVE_STATE" >&2
        exit 1
      fi
      LIVE_STATE=""
    fi
    if [[ -n "$LIVE_STATE" ]]; then
      LEDGER_PATH="$BATCH_DIR/jobs/$ACTIVE_JOB_ID.json"
      if [[ ! -f "$LEDGER_PATH" ]]; then
        echo "live array $ACTIVE_JOB_ID has no task-to-step ledger: $LEDGER_PATH" >&2
        exit 1
      fi
      echo "$ACTIVE_JOB_ID"
      exit 0
    fi
  fi
fi

INCOMPLETE_OUTPUT=$(uv run --no-sync user/tianhaowu/rsci/checkpoint_eval_artifacts.py \
  incomplete-steps "$RUN_DIR")
if [[ -z "$INCOMPLETE_OUTPUT" ]]; then
  echo "all frozen checkpoint evaluations are complete: $RUN_DIR"
  exit 0
fi
mapfile -t INCOMPLETE_STEPS <<<"$INCOMPLETE_OUTPUT"

STEP_MANIFEST=$(mktemp "$BATCH_DIR/steps.XXXXXX")
printf '%s\n' "${INCOMPLETE_STEPS[@]}" >"$STEP_MANIFEST"
LAST_TASK=$((${#INCOMPLETE_STEPS[@]} - 1))
ARRAY_SPEC="0-${LAST_TASK}%${MAX_PARALLEL}"
RUN_LABEL=$(basename "$RUN_DIR")
RUN_LABEL=${RUN_LABEL#base-op10-40-strict-r128-}

SBATCH_ARGS=(
  --parsable
  --job-name="rsci-frozen-${RUN_LABEL}"
  --array="$ARRAY_SPEC"
  --output="$BATCH_DIR/job_%A_%a.log"
)
if [[ -n "$DEPENDENCY" ]]; then
  SBATCH_ARGS+=(--dependency="$DEPENDENCY")
fi

SUBMISSION=$(env -u SBATCH_OUTPUT -u SBATCH_ERROR sbatch \
  "${SBATCH_ARGS[@]}" \
  user/tianhaowu/rsci/scripts/run_rl_checkpoint_eval_array.sbatch \
  "$RUN_DIR" "$STEP_MANIFEST")
JOB_ID=${SUBMISSION%%;*}
if [[ ! "$JOB_ID" =~ ^[0-9]+$ ]]; then
  echo "sbatch returned an invalid job id: $SUBMISSION" >&2
  exit 1
fi

ACTIVE_JOB_PARTIAL="$ACTIVE_JOB_PATH.partial"
printf '%s\n' "$JOB_ID" >"$ACTIVE_JOB_PARTIAL"
mv "$ACTIVE_JOB_PARTIAL" "$ACTIVE_JOB_PATH"

LEDGER_ARGS=(
  write-job-ledger
  "$RUN_DIR"
  "$JOB_ID"
  "$STEP_MANIFEST"
  --max-parallel "$MAX_PARALLEL"
)
if [[ -n "$DEPENDENCY" ]]; then
  LEDGER_ARGS+=(--dependency "$DEPENDENCY")
fi
uv run --no-sync user/tianhaowu/rsci/checkpoint_eval_artifacts.py "${LEDGER_ARGS[@]}" >/dev/null
echo "$JOB_ID"
