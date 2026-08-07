#!/usr/bin/env bash
set -euo pipefail

LIVE_REPO_ROOT=/storage/home/tianhaowu/prime-rl
RUN_DIR=${1:?usage: submit_rl_checkpoint_eval.sh RUN_DIR STEP}
STEP=${2:?usage: submit_rl_checkpoint_eval.sh RUN_DIR STEP}

cd "$LIVE_REPO_ROOT"
RUN_DIR=$(realpath "$RUN_DIR")
SOURCE_BOOTSTRAP="$RUN_DIR/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot.sh"
if [[ ! -f "$SOURCE_BOOTSTRAP" ]]; then
  echo "frozen source bootstrap does not exist: $SOURCE_BOOTSTRAP" >&2
  exit 1
fi
source "$SOURCE_BOOTSTRAP" "$RUN_DIR"
REPO_ROOT=$RSCI_SOURCE_SNAPSHOT
cd "$REPO_ROOT"
EVAL_CONFIG=$(uv run --no-sync user/tianhaowu/rsci/prepare_rl_checkpoint_eval.py "$RUN_DIR" "$STEP")
OUTPUT_DIR=$(dirname "$(dirname "$EVAL_CONFIG")")
RUN_NAME=$(basename "$RUN_DIR")
JOB_NAME="rsci-eval-${RUN_NAME##*-}-s${STEP}"

env -u SBATCH_OUTPUT -u SBATCH_ERROR sbatch \
  --parsable \
  --job-name="$JOB_NAME" \
  --nodes=1 \
  --ntasks-per-node=1 \
  --gres=gpu:1 \
  --cpus-per-task=16 \
  --mem=64G \
  --time=04:00:00 \
  --output="$OUTPUT_DIR/job_%j.log" \
  user/tianhaowu/rsci/scripts/run_eval.sbatch "$EVAL_CONFIG" "$RUN_DIR"
