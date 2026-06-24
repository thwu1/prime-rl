#!/bin/bash
#SBATCH --job-name=vmvm-push
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=04:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --array=0-99
#SBATCH --output=/checkpoint/ram/tianhaowu/vmvm_push_logs/push_%A_%a.log
#SBATCH --error=/checkpoint/ram/tianhaowu/vmvm_push_logs/push_%A_%a.log

# Each array task processes a slice of ~178 images.
# 17792 tasks / 100 workers = 178 per worker (last worker picks up remainder).

set -u

TASK_FILE="/checkpoint/ram/tianhaowu/vmvm_push_all_tasks.txt"
TOTAL_TASKS=$(wc -l < "$TASK_FILE")
NUM_WORKERS=100
PER_WORKER=$(( (TOTAL_TASKS + NUM_WORKERS - 1) / NUM_WORKERS ))
START=$(( SLURM_ARRAY_TASK_ID * PER_WORKER ))

echo "=== Worker ${SLURM_ARRAY_TASK_ID}/${NUM_WORKERS}: offset=${START} count=${PER_WORKER} ==="
exec bash /storage/home/tianhaowu/prime-rl/user/tianhaowu/fair-sc-3/scripts/push_vmvm_batch.sh \
    "$TASK_FILE" "$START" "$PER_WORKER"
