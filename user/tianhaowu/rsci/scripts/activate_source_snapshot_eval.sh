#!/usr/bin/env bash

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "activate_source_snapshot_eval.sh must be sourced" >&2
  exit 2
fi

RSCI_RUN_DIR=${1:?usage: source activate_source_snapshot_eval.sh RUN_DIR}
RSCI_RUN_DIR=$(realpath "$RSCI_RUN_DIR")
RSCI_ACTIVATE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
RSCI_SOURCE_ROOT=$(realpath "$RSCI_ACTIVATE_DIR/../../../..")
RSCI_EXPECTED_SOURCE=$(realpath "$RSCI_RUN_DIR/source_snapshot")

if [[ "$RSCI_SOURCE_ROOT" != "$RSCI_EXPECTED_SOURCE" ]]; then
  echo "source snapshot path mismatch: bootstrap=$RSCI_SOURCE_ROOT expected=$RSCI_EXPECTED_SOURCE" >&2
  return 1
fi
if [[ ! -f "$RSCI_RUN_DIR/source_provenance.json" ]]; then
  echo "source provenance is missing: $RSCI_RUN_DIR/source_provenance.json" >&2
  return 1
fi
if [[ ! -L "$RSCI_SOURCE_ROOT/.venv" ]]; then
  echo "source snapshot has no shared .venv link: $RSCI_SOURCE_ROOT/.venv" >&2
  return 1
fi

export RSCI_SOURCE_SNAPSHOT="$RSCI_SOURCE_ROOT"
export RSCI_LIVE_REPO_ROOT=/storage/home/tianhaowu/prime-rl
export UV_PROJECT_ENVIRONMENT=$(realpath "$RSCI_SOURCE_ROOT/.venv")
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1

RSCI_SNAPSHOT_PYTHONPATH=(
  "$RSCI_SOURCE_ROOT/user/tianhaowu/rsci/source_runtime"
  "$RSCI_SOURCE_ROOT/src"
  "$RSCI_SOURCE_ROOT/packages/prime-rl-configs/src"
  "$RSCI_SOURCE_ROOT/deps/pydantic-config/src"
  "$RSCI_SOURCE_ROOT/deps/renderers"
  "$RSCI_SOURCE_ROOT/deps/verifiers"
  "$RSCI_SOURCE_ROOT/user/tianhaowu/rsci"
)
RSCI_SNAPSHOT_PATH=$(IFS=:; echo "${RSCI_SNAPSHOT_PYTHONPATH[*]}")
export PYTHONPATH="$RSCI_SNAPSHOT_PATH"
unset RSCI_SNAPSHOT_PATH RSCI_SNAPSHOT_PYTHONPATH RSCI_ACTIVATE_DIR RSCI_EXPECTED_SOURCE

source "$RSCI_SOURCE_ROOT/.venv/bin/activate"
cd "$RSCI_SOURCE_ROOT"
uv run --no-sync python user/tianhaowu/rsci/source_provenance.py verify-source \
  "$RSCI_RUN_DIR" --expected-source "$RSCI_SOURCE_ROOT"
