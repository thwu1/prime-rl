#!/bin/bash
#SBATCH --job-name=vmvm-push-retry
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=04:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --array=0-49
#SBATCH --output=/checkpoint/ram/tianhaowu/vmvm_push_logs/retry_%A_%a.log
#SBATCH --error=/checkpoint/ram/tianhaowu/vmvm_push_logs/retry_%A_%a.log

set -u

TASK_FILE="/checkpoint/ram/tianhaowu/vmvm_push_remaining.txt"
TOTAL_TASKS=$(wc -l < "$TASK_FILE")
NUM_WORKERS=50
PER_WORKER=$(( (TOTAL_TASKS + NUM_WORKERS - 1) / NUM_WORKERS ))
START=$(( SLURM_ARRAY_TASK_ID * PER_WORKER ))

echo "=== Retry worker ${SLURM_ARRAY_TASK_ID}/${NUM_WORKERS}: offset=${START} count=${PER_WORKER} ==="
exec bash /storage/home/tianhaowu/prime-rl/user/tianhaowu/fair-sc-3/scripts/push_vmvm_batch.sh \
    "$TASK_FILE" "$START" "$PER_WORKER"
