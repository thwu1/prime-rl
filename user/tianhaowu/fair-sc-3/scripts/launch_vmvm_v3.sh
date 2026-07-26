#!/usr/bin/env bash
# Preflight and submit the OptimBench V3 DockerHub-to-VMVM mirror.

set -euo pipefail

TASK_FILE="${TASK_FILE:-/storage/home/tianhaowu/meta_opt/optimbench/tb/accepted_tasks_20260710_run.txt}"
DOCKER_DONE_DIR="${DOCKER_DONE_DIR:-/home/tianhaowu/tb_build_state_v3}"
DONE_FILE="${DONE_FILE:-/checkpoint/ram/tianhaowu/vmvm_push_v3_done.txt}"
FAIL_FILE="${FAIL_FILE:-/checkpoint/ram/tianhaowu/vmvm_push_v3_fail.txt}"
LOG_DIR="${LOG_DIR:-/checkpoint/ram/tianhaowu/vmvm_push_v3_logs}"
DOCKERIO_PREFIX="${DOCKERIO_PREFIX:-docker.io/tianhao0122/optimbench-tb}"
VMVM_PREFIX="${VMVM_PREFIX:-vmvm-registry.fbinfra.net/terminal_bench}"
NUM_WORKERS="${NUM_WORKERS:-100}"
CONCURRENCY="${CONCURRENCY:-100}"
TASK_ATTEMPTS="${TASK_ATTEMPTS:-3}"
RETRY_DELAY="${RETRY_DELAY:-10}"
DRY_RUN="${DRY_RUN:-0}"
ARRAY_SCRIPT="${ARRAY_SCRIPT:-/storage/home/tianhaowu/prime-rl/user/tianhaowu/fair-sc-3/scripts/push_vmvm_array.sbatch}"
BATCH_SCRIPT="${BATCH_SCRIPT:-/storage/home/tianhaowu/prime-rl/user/tianhaowu/fair-sc-3/scripts/push_vmvm_batch.sh}"

[ -f "$TASK_FILE" ] || { echo "Task file not found: $TASK_FILE" >&2; exit 2; }
[ -f "$ARRAY_SCRIPT" ] || { echo "Array script not found: $ARRAY_SCRIPT" >&2; exit 2; }
[ -x "$BATCH_SCRIPT" ] || { echo "Batch script is not executable: $BATCH_SCRIPT" >&2; exit 2; }
[[ "$NUM_WORKERS" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid NUM_WORKERS: $NUM_WORKERS" >&2; exit 2; }
[[ "$CONCURRENCY" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid CONCURRENCY: $CONCURRENCY" >&2; exit 2; }
[[ "$TASK_ATTEMPTS" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid TASK_ATTEMPTS: $TASK_ATTEMPTS" >&2; exit 2; }
[[ "$RETRY_DELAY" =~ ^[0-9]+$ ]] || { echo "Invalid RETRY_DELAY: $RETRY_DELAY" >&2; exit 2; }
[[ "$DRY_RUN" == 0 || "$DRY_RUN" == 1 ]] || { echo "DRY_RUN must be 0 or 1" >&2; exit 2; }
[ "$DONE_FILE" != "$FAIL_FILE" ] || { echo "DONE_FILE and FAIL_FILE must differ" >&2; exit 2; }
[ "$DONE_FILE" != /checkpoint/ram/tianhaowu/vmvm_push_done.txt ] || {
    echo "Refusing to reuse the legacy V2 done file" >&2
    exit 2
}
[ "$FAIL_FILE" != /checkpoint/ram/tianhaowu/vmvm_push_fail.txt ] || {
    echo "Refusing to reuse the legacy V2 fail file" >&2
    exit 2
}

total=$(wc -l < "$TASK_FILE")
nonempty=$(awk 'NF { count++ } END { print count + 0 }' "$TASK_FILE")
unique=$(sort -u "$TASK_FILE" | wc -l)
if (( total == 0 || nonempty != total || unique != total )); then
    echo "Task list must be nonempty, unique, and contain no blank lines: total=$total nonempty=$nonempty unique=$unique" >&2
    exit 2
fi

missing=0
while IFS= read -r task; do
    if [ ! -f "$DOCKER_DONE_DIR/$task.done" ]; then
        ((missing += 1))
        if (( missing <= 20 )); then
            echo "DockerHub push not complete: $task" >&2
        fi
    fi
done < "$TASK_FILE"
if (( missing > 0 )); then
    echo "Refusing VMVM launch: $missing/$total DockerHub pushes are incomplete." >&2
    exit 1
fi

mkdir -p "$LOG_DIR" "$(dirname "$DONE_FILE")" "$(dirname "$FAIL_FILE")"
touch "$DONE_FILE" "$FAIL_FILE"

last=$((NUM_WORKERS - 1))
submit_args=(
    --parsable
    --job-name=vmvm-push-v3
    --array="0-${last}%${CONCURRENCY}"
    --output="$LOG_DIR/push_%A_%a.log"
    --error="$LOG_DIR/push_%A_%a.log"
    --export="ALL,TASK_FILE=$TASK_FILE,NUM_WORKERS=$NUM_WORKERS,DONE_FILE=$DONE_FILE,FAIL_FILE=$FAIL_FILE,DOCKERIO_PREFIX=$DOCKERIO_PREFIX,VMVM_PREFIX=$VMVM_PREFIX,TASK_ATTEMPTS=$TASK_ATTEMPTS,RETRY_DELAY=$RETRY_DELAY,BATCH_SCRIPT=$BATCH_SCRIPT"
    "$ARRAY_SCRIPT"
)

if (( DRY_RUN )); then
    printf 'Preflight passed. Launch command:'
    printf ' %q' sbatch "${submit_args[@]}"
    printf '\n'
    exit 0
fi

job_id=$(sbatch "${submit_args[@]}")

echo "Submitted VMVM V3 mirror job $job_id for $total tasks ($NUM_WORKERS workers, concurrency $CONCURRENCY)."
echo "Done file: $DONE_FILE"
echo "Fail file: $FAIL_FILE"
echo "Logs: $LOG_DIR"
