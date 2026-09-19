#!/bin/bash
#SBATCH --job-name=k3-smoke-recovery
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_smoke_recovery_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_smoke_recovery_%j.log

set -euo pipefail
umask 077

if (( $# != 0 )); then
    printf 'Configure the Kimi smoke recovery through environment variables\n' >&2
    exit 2
fi
if [[ ${RESUME_DIR+x} ]]; then
    printf 'Kimi smoke recovery requires a fresh namespace; RESUME_DIR must be unset\n' >&2
    exit 2
fi

project_dir=${PROJECT_DIR:?Set PROJECT_DIR to the reviewed clean source snapshot}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
expected_prime_rl_commit=${EVAL_EXPECTED_PRIME_RL_REVISION:?Set EVAL_EXPECTED_PRIME_RL_REVISION}
mode=${KIMI_SMOKE_RECOVERY_MODE:?Set KIMI_SMOKE_RECOVERY_MODE to one or fresh-two}
output_dir=${OUTPUT_DIR:?Set OUTPUT_DIR to a new run directory}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
python_bin=${PYTHON_BIN_X86_64:-python3}
export VACLI_LEASE_RETRIES=${VACLI_LEASE_RETRIES:-20}
export VACLI_MAX_PULL_RETRIES=${VACLI_MAX_PULL_RETRIES:-20}
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=${VACLI_IMAGE_PULL_TIMEOUT_SECONDS:-3600}
export VACLI_CONTAINER_PRIVILEGED=${VACLI_CONTAINER_PRIVILEGED:-1}
export VACLI_BIN=${VACLI_BIN:-/public/fbpkgs/x86_64/vacli/stable/vacli}

if [[ "$(readlink -f -- "$0")" != "$(readlink -f -- "$workflow_dir/run_kimi_smoke_recovery.sbatch")" ]]; then
    printf 'Recovery launcher must execute from PROJECT_DIR\n' >&2
    exit 2
fi
if [[ -e "$output_dir" ]]; then
    printf 'OUTPUT_DIR must be a new recovery namespace\n' >&2
    exit 2
fi
if [[ ! -x "$x86_uv" || "$(uname -m)" != x86_64 || ! -d "$x86_site/pydantic" ]]; then
    printf 'Missing reviewed x86_64 evaluation runtime\n' >&2
    exit 2
fi
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site${PYTHONPATH:+:$PYTHONPATH}"

case "$mode" in
    one)
        selection=${KIMI_SMOKE_RECOVERY_SELECTION:?Set KIMI_SMOKE_RECOVERY_SELECTION}
        selection_dir=$(dirname -- "$selection")
        approved_task_file="$selection_dir/approved_task.txt"
        eval_config="$selection_dir/config.toml"
        approved_task_sha256=$(sha256sum -- "$approved_task_file" | cut -d' ' -f1)
        eval_config_sha256=$(sha256sum -- "$eval_config" | cut -d' ' -f1)
        composite_output_dir=${KIMI_SMOKE_COMPOSITE_OUTPUT_DIR:?Set KIMI_SMOKE_COMPOSITE_OUTPUT_DIR}
        deployment_id=${EVAL_DEPLOYMENT_ID:?Set EVAL_DEPLOYMENT_ID}
        deployment_spec=${INFERENCE_DEPLOYMENT_SPEC:?Set INFERENCE_DEPLOYMENT_SPEC}
        deployment_spec_sha256=${INFERENCE_DEPLOYMENT_SPEC_SHA256:?Set INFERENCE_DEPLOYMENT_SPEC_SHA256}
        readiness_checkpoint=${INFERENCE_READINESS_CHECKPOINT:?Set INFERENCE_READINESS_CHECKPOINT}
        readiness_checkpoint_sha256=${INFERENCE_READINESS_CHECKPOINT_SHA256:?Set INFERENCE_READINESS_CHECKPOINT_SHA256}
        proxy_info=${INFERENCE_PROXY_INFO:?Set INFERENCE_PROXY_INFO}
        proxy_info_sha256=${INFERENCE_PROXY_INFO_SHA256:?Set INFERENCE_PROXY_INFO_SHA256}
        expected_traces=1
        export VACLI_MAX_CONCURRENT_LEASES=1
        "$x86_uv" run --no-project --offline --python "$python_bin" \
            python3 "$workflow_dir/smoke_timeout_recovery.py" verify-launch \
            --selection "$selection" \
            --output-dir "$output_dir" \
            --task-file "$approved_task_file" \
            --task-file-sha256 "$approved_task_sha256" \
            --config-file "$eval_config" \
            --config-file-sha256 "$eval_config_sha256" \
            --project-root "$project_dir" \
            --expected-prime-rl-commit "$expected_prime_rl_commit" \
            --deployment-id "$deployment_id" \
            --deployment-spec "$deployment_spec" \
            --deployment-spec-sha256 "$deployment_spec_sha256" \
            --readiness-checkpoint "$readiness_checkpoint" \
            --readiness-checkpoint-sha256 "$readiness_checkpoint_sha256" \
            --proxy-info "$proxy_info" \
            --proxy-info-sha256 "$proxy_info_sha256" \
            --vacli-bin "$VACLI_BIN" \
            --vacli-max-concurrent-leases "$VACLI_MAX_CONCURRENT_LEASES" \
            --vacli-lease-retries "$VACLI_LEASE_RETRIES" \
            --vacli-max-pull-retries "$VACLI_MAX_PULL_RETRIES" \
            --vacli-image-pull-timeout-seconds "$VACLI_IMAGE_PULL_TIMEOUT_SECONDS" \
            --vacli-container-privileged "$VACLI_CONTAINER_PRIVILEGED" >/dev/null
        if [[ -e "$composite_output_dir" ]]; then
            printf 'Composite output must use a new namespace\n' >&2
            exit 2
        fi
        ;;
    fresh-two)
        approved_task_file="$workflow_dir/configs/eval/tb4_kimi_token_smoke.tasks.txt"
        approved_task_sha256=ecdcbc6e4f54b690e64b4566de5eecf33467088c8ca3436738cd7308d4e45b83
        eval_config="$workflow_dir/configs/eval/tb4_kimi_k3_fresh_smoke12h.toml"
        eval_config_sha256=$(sha256sum -- "$eval_config" | cut -d' ' -f1)
        expected_traces=2
        export VACLI_MAX_CONCURRENT_LEASES=2
        unset KIMI_SMOKE_RECOVERY_SELECTION KIMI_SMOKE_COMPOSITE_OUTPUT_DIR
        ;;
    *)
        printf 'KIMI_SMOKE_RECOVERY_MODE must be one or fresh-two\n' >&2
        exit 2
        ;;
esac

export EVAL_RUN_ROLE=smoke
export EVAL_CONFIG="$eval_config"
export EVAL_CONFIG_SHA256="$eval_config_sha256"
export EVAL_APPROVED_TASK_FILE="$approved_task_file"
export EVAL_APPROVED_TASK_FILE_SHA256="$approved_task_sha256"
unset INFERENCE_SMOKE_CHECKPOINT INFERENCE_SMOKE_CHECKPOINT_SHA256

bash "$workflow_dir/run_eval.sbatch"

env \
    PROJECT_DIR="$project_dir" \
    RESULTS_DIR="$output_dir" \
    SMOKE_TASK_FILE="$approved_task_file" \
    SMOKE_TASK_FILE_SHA256="$approved_task_sha256" \
    SMOKE_EXPECTED_TRACES="$expected_traces" \
    SMOKE_REQUIRE_EXACT_PROVIDER_JSON=1 \
    bash "$workflow_dir/run_trace_smoke_audit.sbatch"

if [[ "$mode" == one ]]; then
    "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/smoke_timeout_recovery.py" combine \
        --selection "$selection" \
        --recovery-checkpoint "$output_dir/smoke_checkpoint.json" \
        --namespace "$composite_output_dir"
else
    printf '{"counts":{"tasks":2,"traces":2},"ok":true,"state":"passed"}\n'
fi
