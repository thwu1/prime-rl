#!/usr/bin/bash -p
set +x
set -euo pipefail

project_dir=${PROJECT_DIR:?Set PROJECT_DIR}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
output_dir=${OUTPUT_DIR:?Set OUTPUT_DIR}
expected_count=${DIRECT_KIMI_APPROVED_TASK_COUNT:?Set DIRECT_KIMI_APPROVED_TASK_COUNT}
resume_attempts=${DIRECT_KIMI_ZERO_MODEL_RESUME_ATTEMPTS:-1}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}

[[ "$expected_count" =~ ^[1-9][0-9]*$ \
    && "$resume_attempts" =~ ^[0-9]+$ \
    && "$resume_attempts" -le 1 \
    && "$output_dir" == /* \
    && -f "$workflow_dir/assess_zero_model_resume.py" ]] \
    || { printf '{"code":"zero_model_resume_configuration_invalid","state":"blocked"}\n' >&2; exit 2; }

for (( attempt = 0; ; attempt++ )); do
    set +e
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 -c 'from verifiers.v1.cli.eval.main import main; main()' --resume "$output_dir"
    eval_status=$?
    set -e
    [[ "$eval_status" -eq 0 ]] || exit "$eval_status"

    assessment=$(
        "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$workflow_dir/assess_zero_model_resume.py" \
            --results "$output_dir/results.jsonl" \
            --expected-count "$expected_count" --format tsv
    ) || exit $?
    IFS=$'\t' read -r state observed errors missing extra <<< "$assessment"
    if [[ -n "$extra" || "$assessment" == *$'\n'* \
        || ! "$observed" =~ ^[0-9]+$ || ! "$errors" =~ ^[0-9]+$ \
        || ! "$missing" =~ ^[0-9]+$ ]]; then
        printf '{"code":"zero_model_resume_assessment_invalid","state":"blocked"}\n' >&2
        exit 2
    fi
    printf '{"attempt":%s,"missing_rows":%s,"observed_rows":%s,"state":"%s","zero_model_error_rows":%s}\n' \
        "$attempt" "$missing" "$observed" "$state" "$errors"
    [[ "$state" == complete ]] && exit 0
    if [[ "$state" != resume_required || "$attempt" -ge "$resume_attempts" ]]; then
        printf '{"code":"zero_model_resume_budget_exhausted","state":"blocked"}\n' >&2
        exit 2
    fi
done
