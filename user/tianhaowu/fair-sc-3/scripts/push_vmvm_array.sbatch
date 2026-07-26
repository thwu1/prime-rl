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

# Each array task processes one evenly sized slice of the selected task file.

set -u

TASK_FILE="${TASK_FILE:-/checkpoint/ram/tianhaowu/vmvm_push_all_tasks.txt}"
BATCH_SCRIPT="${BATCH_SCRIPT:-/storage/home/tianhaowu/prime-rl/user/tianhaowu/fair-sc-3/scripts/push_vmvm_batch.sh}"
NUM_WORKERS="${NUM_WORKERS:-100}"

[ -f "$TASK_FILE" ] || { echo "Task file not found: $TASK_FILE" >&2; exit 2; }
[ -x "$BATCH_SCRIPT" ] || { echo "Batch script is not executable: $BATCH_SCRIPT" >&2; exit 2; }
[[ "$NUM_WORKERS" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid NUM_WORKERS: $NUM_WORKERS" >&2; exit 2; }
(( SLURM_ARRAY_TASK_ID < NUM_WORKERS )) || {
    echo "Array index $SLURM_ARRAY_TASK_ID is outside NUM_WORKERS=$NUM_WORKERS" >&2
    exit 2
}

TOTAL_TASKS=$(wc -l < "$TASK_FILE")
(( TOTAL_TASKS > 0 )) || { echo "Task file is empty: $TASK_FILE" >&2; exit 2; }
PER_WORKER=$(( (TOTAL_TASKS + NUM_WORKERS - 1) / NUM_WORKERS ))
START=$(( SLURM_ARRAY_TASK_ID * PER_WORKER ))

echo "=== Worker ${SLURM_ARRAY_TASK_ID}/${NUM_WORKERS}: offset=${START} count=${PER_WORKER} ==="
exec "$BATCH_SCRIPT" \
    "$TASK_FILE" "$START" "$PER_WORKER"
