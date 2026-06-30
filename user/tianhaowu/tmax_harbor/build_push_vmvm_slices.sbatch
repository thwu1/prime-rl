#!/bin/bash
#SBATCH --job-name=tmax-build500
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=08:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --array=0-49
#SBATCH --output=/checkpoint/ram/tianhaowu/tmax_build_logs/build500_%A_%a.log
#SBATCH --error=/checkpoint/ram/tianhaowu/tmax_build_logs/build500_%A_%a.log

# Slice build: 50 workers, each builds ~10 tasks from the 500-task list on its own
# leased VMVM VM, pushing to vmvm-registry. TASK_FILE overridable via --export.
set -u
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export VACLI_LEASE_RETRIES=10 VACLI_MAX_PULL_RETRIES=12

TASK_FILE="${TASK_FILE:-/checkpoint/ram/tianhaowu/tmax_full500.txt}"
NUM_WORKERS=50
TOTAL=$(grep -cve '^[[:space:]]*$' "$TASK_FILE")
PER=$(( (TOTAL + NUM_WORKERS - 1) / NUM_WORKERS ))
START=$(( SLURM_ARRAY_TASK_ID * PER ))
SLICE="/checkpoint/ram/tianhaowu/tmax_build_logs/slice500_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}.txt"
sed -n "$((START + 1)),$((START + PER))p" "$TASK_FILE" > "$SLICE"
echo "=== worker ${SLURM_ARRAY_TASK_ID}: tasks $((START+1))..$((START+PER)) ($(grep -c . "$SLICE")) ==="
exec bash /storage/home/tianhaowu/prime-rl/user/tianhaowu/tmax_harbor/build_push_vmvm.sh "$SLICE"
