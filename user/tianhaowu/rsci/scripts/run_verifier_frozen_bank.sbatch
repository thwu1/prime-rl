#!/usr/bin/env bash
#SBATCH --job-name=rsci-verifier-bank
#SBATCH --qos=h100_lowest
#SBATCH --account=ram
#SBATCH --partition=h100
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:8
#SBATCH --cpus-per-task=64
#SBATCH --mem=256G
#SBATCH --time=04:00:00
#SBATCH --requeue

set -euo pipefail

CONFIG_REPO_PATH=${1:?usage: run_verifier_frozen_bank.sbatch EVAL_CONFIG_REPO_PATH SOURCE_RUN_DIR}
RUN_DIR=${2:?usage: run_verifier_frozen_bank.sbatch EVAL_CONFIG_REPO_PATH SOURCE_RUN_DIR}
RUN_DIR=$(realpath "$RUN_DIR")
SOURCE_BOOTSTRAP="$RUN_DIR/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot_eval.sh"

if [[ ! -f "$SOURCE_BOOTSTRAP" ]]; then
  echo "frozen evaluation source bootstrap does not exist: $SOURCE_BOOTSTRAP" >&2
  exit 1
fi

source "$SOURCE_BOOTSTRAP" "$RUN_DIR"
cd "$RSCI_SOURCE_SNAPSHOT"
if [[ "$CONFIG_REPO_PATH" == /* || "$CONFIG_REPO_PATH" =~ (^|/)\.\.(/|$) ]]; then
  echo "evaluation config must be a repository-relative path without '..': $CONFIG_REPO_PATH" >&2
  exit 2
fi
if ! CONFIG=$(realpath -e -- "$RSCI_SOURCE_SNAPSHOT/$CONFIG_REPO_PATH"); then
  echo "evaluation config does not exist in the source snapshot: $CONFIG_REPO_PATH" >&2
  exit 1
fi
case "$CONFIG" in
  "$RSCI_SOURCE_SNAPSHOT"/*) ;;
  *)
    echo "evaluation config escapes the source snapshot: $CONFIG_REPO_PATH" >&2
    exit 2
    ;;
esac
if [[ ! -f "$CONFIG" ]]; then
  echo "evaluation config is not a file in the source snapshot: $CONFIG_REPO_PATH" >&2
  exit 1
fi

PINNED_REFERENCE_OUTPUT=$(uv run --no-sync python - "$CONFIG" <<'PY'
import sys
import tomllib
from pathlib import Path

config_path = Path(sys.argv[1])
with config_path.open("rb") as handle:
    config = tomllib.load(handle)
for field in ("infer_config", "evaluator"):
    value = config.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"evaluation config must define a non-empty {field}")
    print(value)
PY
)
mapfile -t PINNED_REFERENCES <<<"$PINNED_REFERENCE_OUTPUT"
unset PINNED_REFERENCE_OUTPUT
for reference in "${PINNED_REFERENCES[@]}"; do
  if [[ "$reference" == /* || "$reference" =~ (^|/)\.\.(/|$) ]]; then
    echo "nested evaluation references must be repository-relative paths without '..': $reference" >&2
    exit 2
  fi
  if ! RESOLVED_REFERENCE=$(realpath -e -- "$RSCI_SOURCE_SNAPSHOT/$reference"); then
    echo "nested evaluation reference does not exist in the source snapshot: $reference" >&2
    exit 1
  fi
  case "$RESOLVED_REFERENCE" in
    "$RSCI_SOURCE_SNAPSHOT"/*) ;;
    *)
      echo "nested evaluation reference escapes the source snapshot: $reference" >&2
      exit 2
      ;;
  esac
  if [[ ! -f "$RESOLVED_REFERENCE" ]]; then
    echo "nested evaluation reference is not a file: $reference" >&2
    exit 1
  fi
done

exec bash user/tianhaowu/rsci/scripts/run_eval.sh "$CONFIG"
