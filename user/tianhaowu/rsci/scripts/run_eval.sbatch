#!/bin/bash
#SBATCH --job-name=rsci-eval
#SBATCH --qos=h100_ram_high
#SBATCH --account=ram
#SBATCH --partition=h100
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:8
#SBATCH --cpus-per-task=64
#SBATCH --mem=256G
#SBATCH --time=04:00:00
#SBATCH --output=/checkpoint/ram-h100-2/tianhaowu/prime-rl-smoke/rsci_eval_%j.log

set -euo pipefail

CONFIG=${1:?usage: run_eval.sbatch EVAL_CONFIG [FROZEN_RUN_DIR]}
RUN_DIR=${2:-}
if [[ -n "$RUN_DIR" ]]; then
  RUN_DIR=$(realpath "$RUN_DIR")
  SOURCE_BOOTSTRAP="$RUN_DIR/source_snapshot/user/tianhaowu/rsci/scripts/activate_source_snapshot.sh"
  if [[ ! -f "$SOURCE_BOOTSTRAP" ]]; then
    echo "frozen source bootstrap does not exist: $SOURCE_BOOTSTRAP" >&2
    exit 1
  fi
  source "$SOURCE_BOOTSTRAP" "$RUN_DIR"
  cd "$RSCI_SOURCE_SNAPSHOT"
else
  cd /storage/home/tianhaowu/prime-rl
fi
exec bash user/tianhaowu/rsci/scripts/run_eval.sh "$CONFIG"
