#!/bin/bash
#SBATCH --job-name=tmax-buildall
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=24:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --array=0-99
#SBATCH --output=/checkpoint/ram/tianhaowu/tmax_build_logs/buildall_%A_%a.log
#SBATCH --error=/checkpoint/ram/tianhaowu/tmax_build_logs/buildall_%A_%a.log

# Build ALL remaining TMax->harbor images: 100 workers, each builds a slice on its
# own leased VMVM VM, pushing to vmvm-registry. Resumable: build_push_vmvm.sh skips
# tasks already in the shared done-file. TASK_FILE overridable via --export.
set -u
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export VACLI_LEASE_RETRIES=10 VACLI_MAX_PULL_RETRIES=12

TASK_FILE="${TASK_FILE:-/checkpoint/ram/tianhaowu/tmax_remaining.txt}"
NUM_WORKERS="${SLURM_ARRAY_TASK_COUNT:-100}"
TOTAL=$(grep -cve '^[[:space:]]*$' "$TASK_FILE")
PER=$(( (TOTAL + NUM_WORKERS - 1) / NUM_WORKERS ))
START=$(( SLURM_ARRAY_TASK_ID * PER ))
SLICE="/checkpoint/ram/tianhaowu/tmax_build_logs/sliceall_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}.txt"
sed -n "$((START + 1)),$((START + PER))p" "$TASK_FILE" > "$SLICE"
echo "=== worker ${SLURM_ARRAY_TASK_ID}: tasks $((START+1))..$((START+PER)) ($(grep -c . "$SLICE")) ==="
exec bash /storage/home/tianhaowu/prime-rl/user/tianhaowu/tmax_harbor/build_push_vmvm.sh "$SLICE"
