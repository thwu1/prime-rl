#!/bin/bash
#SBATCH --job-name=qwen36-swe-rebench-h200
#SBATCH --partition=h200
#SBATCH --qos=h200_ram_high
#SBATCH --account=ram
#SBATCH --time=5-00:00:00
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:4
#SBATCH --no-requeue
#SBATCH --output=/home/tianhaowu/log/slurm-%j.out
#SBATCH --error=/home/tianhaowu/log/slurm-%j.err

set -euo pipefail

project_dir=/storage/home/tianhaowu/prime-rl
export PROJECT_DIR="$project_dir"
export SWEBENCH_INFERENCE_CONFIG="$project_dir/user/tianhaowu/swebench_vmvm/configs/inference/qwen36_h200.toml"
export SWEBENCH_INFERENCE_OUTPUT_ROOT=/checkpoint/ram/tianhaowu/swebench_vmvm/inference/qwen36_h200
export SWEBENCH_INFERENCE_LAUNCHER="$project_dir/user/tianhaowu/swebench_vmvm/run_qwen36_inference_h200.sbatch"
export SWEBENCH_EXPECTED_MODEL=Qwen/Qwen3.6-27B

exec bash "$project_dir/user/tianhaowu/swebench_vmvm/run_inference_4node.sh"
