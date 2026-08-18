#!/bin/bash
#SBATCH --job-name=tmax-build
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=04:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --array=0-9
#SBATCH --output=/checkpoint/ram/tianhaowu/tmax_build_logs/build_%A_%a.log
#SBATCH --error=/checkpoint/ram/tianhaowu/tmax_build_logs/build_%A_%a.log

# Array build: one task image per array index, each leasing its own VMVM VM on its
# own node (resilient to per-node vacli flakiness). TASK_FILE = one task_id per line.
set -u
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export VACLI_LEASE_RETRIES=10 VACLI_MAX_PULL_RETRIES=12

TASK_FILE="${TASK_FILE:-/checkpoint/ram/tianhaowu/tmax_smoke10.txt}"
LINE=$((SLURM_ARRAY_TASK_ID + 1))
TASK=$(sed -n "${LINE}p" "$TASK_FILE")
[ -n "$TASK" ] || { echo "no task at line $LINE"; exit 0; }
SLICE="/checkpoint/ram/tianhaowu/tmax_build_logs/slice_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}.txt"
echo "$TASK" > "$SLICE"
echo "=== array worker ${SLURM_ARRAY_TASK_ID}: building $TASK ==="
exec bash /storage/home/tianhaowu/prime-rl/user/tianhaowu/tmax_harbor/build_push_vmvm.sh "$SLICE"
