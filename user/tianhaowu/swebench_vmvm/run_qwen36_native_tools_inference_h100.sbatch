#!/bin/bash
#SBATCH --job-name=qwen36-native-tools-h100
#SBATCH --partition=h100
#SBATCH --qos=h100_ram_high
#SBATCH --account=ram
#SBATCH --time=5-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:8
#SBATCH --exclusive
#SBATCH --no-requeue
#SBATCH --output=/home/tianhaowu/log/slurm-%j.out
#SBATCH --error=/home/tianhaowu/log/slurm-%j.err

set -euo pipefail

project_dir=/storage/home/tianhaowu/prime-rl
config_path="$project_dir/user/tianhaowu/swebench_vmvm/qwen36_native_tools_inference_h100.toml"
output_dir=/checkpoint/ram/tianhaowu/swebench_vmvm/qwen36_native_tools_inference_h100

mkdir -p "$output_dir/logs"
cd "$project_dir"

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1
export HF_HOME=/checkpoint/ram-h100-2/tianhaowu/.cache/huggingface
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export VLLM_ALLOW_LONG_MAX_MODEL_LEN=1
export VLLM_CACHE_ROOT="/tmp/vllm-cache-$USER-$SLURM_JOB_ID"
export FLASHINFER_WORKSPACE_BASE="/tmp/flashinfer-$USER-$SLURM_JOB_ID"

srun --kill-on-bad-exit=1 uv run --no-sync inference @ "$config_path" \
    2>&1 | tee "$output_dir/server_${SLURM_JOB_ID}.log"
