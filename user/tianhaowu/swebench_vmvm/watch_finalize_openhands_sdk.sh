#!/bin/bash

set -euo pipefail

: "${BASE_RESULTS_DIR:?Set BASE_RESULTS_DIR to the OpenHands SDK result directory}"
: "${EVAL_STEP_ID:?Set EVAL_STEP_ID to the active Slurm evaluator step}"

expected_tasks=${EXPECTED_TASKS:-500}
rollouts_per_task=${ROLLOUTS_PER_TASK:-1}
expected_rows=$((expected_tasks * rollouts_per_task))
status_file="$BASE_RESULTS_DIR/finalizer_status.json"
started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
eval_state=unknown
eval_exit_code=unknown

write_status() {
    rc=$?
    trap - EXIT
    completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    rows=0
    if [ -f "$BASE_RESULTS_DIR/results.jsonl" ]; then
        rows=$(wc -l < "$BASE_RESULTS_DIR/results.jsonl")
    fi
    temporary="$status_file.tmp.$$"
    printf '{"eval_step_id":"%s","eval_state":"%s","eval_exit_code":"%s","started_at":"%s","completed_at":"%s","rows":%s,"expected_rows":%s,"exit_code":%s}\n' \
        "$EVAL_STEP_ID" "$eval_state" "$eval_exit_code" "$started_at" "$completed_at" \
        "$rows" "$expected_rows" "$rc" > "$temporary"
    mv "$temporary" "$status_file"
    exit "$rc"
}
trap write_status EXIT

eval_step_is_active() {
    squeue -h -s -j "$EVAL_STEP_ID" -o '%i' | \
        awk -v target="$EVAL_STEP_ID" '$1 == target { found = 1 } END { exit !found }'
}

while eval_step_is_active; do
    rows=$(wc -l < "$BASE_RESULTS_DIR/results.jsonl")
    printf '%s OpenHands SDK progress: %s/%s rows\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$rows" "$expected_rows"
    sleep 60
done

for ((attempt = 1; attempt <= 30; attempt++)); do
    if eval_record=$(sacct -n -P -j "$EVAL_STEP_ID" --format=JobIDRaw,State,ExitCode | \
        awk -F'|' -v target="$EVAL_STEP_ID" '$1 == target {print $2 "|" $3; exit}'); then
        IFS='|' read -r eval_state eval_exit_code <<< "$eval_record"
        case "$eval_state" in
            "" | PENDING | RUNNING | COMPLETING | CONFIGURING)
                ;;
            *)
                break
                ;;
        esac
    fi
    sleep 2
done
if [ "$eval_state" = unknown ] || [ -z "$eval_state" ]; then
    printf 'No terminal Slurm accounting record found for evaluator step %s\n' \
        "$EVAL_STEP_ID" >&2
    exit 1
fi
if [ "$eval_state" != COMPLETED ] || [ "$eval_exit_code" != 0:0 ]; then
    printf 'Evaluator step %s ended as %s with exit code %s\n' \
        "$EVAL_STEP_ID" "$eval_state" "$eval_exit_code" >&2
    exit 1
fi

rows=$(wc -l < "$BASE_RESULTS_DIR/results.jsonl")
if [ "$rows" -ne "$expected_rows" ]; then
    printf 'Evaluator step %s exited with %s/%s rows\n' "$EVAL_STEP_ID" "$rows" "$expected_rows" >&2
    exit 1
fi

export BASE_RESULTS_DIR EXPECTED_TASKS="$expected_tasks" ROLLOUTS_PER_TASK="$rollouts_per_task"
bash "$script_dir/finalize_openhands_sdk.sh"
