#!/bin/bash
#SBATCH --job-name=rsci-oracle-dataset
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --output=/home/tianhaowu/log/slurm-%j.out
#SBATCH --error=/home/tianhaowu/log/slurm-%j.out

set -euo pipefail

cd /storage/home/tianhaowu/prime-rl

SOURCE_ROOT=${1:?usage: sbatch run_oracle_dataset.sbatch SOURCE_ROOT OUTPUT_ROOT THROUGH_OPERATION TOKENIZER}
OUTPUT_ROOT=${2:?usage: sbatch run_oracle_dataset.sbatch SOURCE_ROOT OUTPUT_ROOT THROUGH_OPERATION TOKENIZER}
THROUGH_OPERATION=${3:?usage: sbatch run_oracle_dataset.sbatch SOURCE_ROOT OUTPUT_ROOT THROUGH_OPERATION TOKENIZER}
TOKENIZER=${4:?usage: sbatch run_oracle_dataset.sbatch SOURCE_ROOT OUTPUT_ROOT THROUGH_OPERATION TOKENIZER}

export HF_HUB_OFFLINE=1
export PYTHONDONTWRITEBYTECODE=1
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

exec uv run --no-sync user/tianhaowu/rsci/frontier_build_oracle_dataset.py \
  --source-root "$SOURCE_ROOT" \
  --output-root "$OUTPUT_ROOT" \
  --through-operation "$THROUGH_OPERATION" \
  --tokenizer "$TOKENIZER"
