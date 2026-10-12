#!/bin/bash
#SBATCH --job-name=swebench-ohsdk-setup
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=06:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/swebench_vmvm/logs/openhands_sdk_setup_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/swebench_vmvm/logs/openhands_sdk_setup_%j.log

set -euo pipefail

project_dir=/storage/home/tianhaowu/prime-rl
setup_root=/checkpoint/ram/tianhaowu/swebench_vmvm/openhands_sdk_setup

mkdir -p /checkpoint/ram/tianhaowu/swebench_vmvm/logs "$setup_root"
cd "$project_dir"

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export SETUP_ROOT="$setup_root"

bash user/tianhaowu/swebench_vmvm/setup_openhands_sdk.sh
