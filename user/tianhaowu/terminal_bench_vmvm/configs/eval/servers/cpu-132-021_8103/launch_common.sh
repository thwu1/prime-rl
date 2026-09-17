#!/bin/bash
set -euo pipefail
umask 077

if (( $# != 1 )) || [[ $1 != mobius && $1 != tb4 ]]; then
    printf 'The shared Kimi launch helper requires one pinned profile\n' >&2
    exit 2
fi
profile=$1

for forbidden in \
    DIRECT_QWEN_APPROVED_TASK_FILE \
    DIRECT_QWEN_APPROVED_TASK_FILE_SHA256 \
    EVAL_APPROVED_TASK_FILE \
    EVAL_APPROVED_TASK_FILE_SHA256 \
    EVAL_CONFIG \
    EVAL_CONFIG_SHA256 \
    EVAL_DATASET_ARCHIVE \
    EVAL_DATASET_ARCHIVE_SHA256 \
    EVAL_DATASET_CONTENT_SHA256 \
    EVAL_DATASET_REVISION \
    EVAL_DEPLOYMENT_ID \
    EVAL_EXPECTED_MODEL \
    EVAL_EXPECTED_PRIME_RL_REVISION \
    EVAL_MODEL \
    EVAL_PROMOTION_CERTIFICATE \
    EVAL_PROMOTION_CERTIFICATE_SHA256 \
    EVAL_RUN_ROLE \
    INFERENCE_BASE_URL \
    INFERENCE_DEPLOYMENT_ID \
    INFERENCE_DEPLOYMENT_SPEC \
    INFERENCE_DEPLOYMENT_SPEC_SHA256 \
    INFERENCE_JOB_ID \
    INFERENCE_PROXY_INFO \
    INFERENCE_PROXY_INFO_SHA256 \
    INFERENCE_PROXY_URL \
    INFERENCE_READINESS_CHECKPOINT \
    INFERENCE_READINESS_CHECKPOINT_SHA256 \
    INFERENCE_SMOKE_CHECKPOINT \
    INFERENCE_SMOKE_CHECKPOINT_SHA256 \
    KIMI_SHARED_RESUME_DIR \
    KIMI_SHARED_WRITER_LOCK_FD \
    OPENAI_API_KEY \
    OUTPUT_DIR \
    RESUME_DIR; do
    if [[ -v $forbidden ]]; then
        printf '%s is forbidden for the pinned shared Kimi launcher\n' "$forbidden" >&2
        exit 2
    fi
done
if [[ -n ${VACLI_MAX_CONCURRENT_LEASES:-} && ${VACLI_MAX_CONCURRENT_LEASES} != 2 ]]; then
    printf 'VACLI_MAX_CONCURRENT_LEASES must be exactly 2 for shared Kimi\n' >&2
    exit 2
fi
if [[ ! ${SLURM_JOB_ID:-} =~ ^[1-9][0-9]*$ ]]; then
    printf 'The shared Kimi launcher requires a numeric SLURM_JOB_ID\n' >&2
    exit 2
fi

project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
server_dir="$workflow_dir/configs/eval/servers/cpu-132-021_8103"
python_bin=${PYTHON_BIN_X86_64:-python3}
x86_site=${PYTHON_SITE_X86_64:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/python_x86_64}
x86_uv=${UV_BIN_X86_64:-/storage/home/tianhaowu/.local/x86_64/bin/uv}
actual_server_dir=$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
if [[ "$actual_server_dir" != "$server_dir" ]]; then
    printf 'The shared Kimi helper must run from its pinned project tree\n' >&2
    exit 2
fi
if [[ ! -x "$x86_uv" || "$(uname -m)" != x86_64 || ! -d "$x86_site/pydantic" ]]; then
    printf 'Missing pinned x86_64 Python runtime/dependencies\n' >&2
    exit 2
fi

deployment_id=shared-kimi-k3
deployment_root=/checkpoint/ram/shared/vllm_deployments_v2/shared-kimi-k3
deployment_spec="$deployment_root/spec.yaml"
deployment_spec_sha256=ab00213a43083eba87f8b5999a3046e8d27ebe42b933ee845fd0cf4928b266e2

case "$profile" in
    mobius)
        eval_config="$server_dir/mobius_kimi_k3_shared24_2500.toml"
        approved_task_file="$workflow_dir/configs/eval/mobius_valid_tasks_2500.txt"
        approved_task_file_sha256=d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b
        expected_config_sha256=cfe7891a16f175187d2e892f1293471a1626f3ebda33e9f3d9ae8aab223a7937
        expected_rollout_cap=64
        expected_http_cap=24
        expected_waiting_cap=40
        dataset_revision=ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366
        output_prefix=mobius_kimi_k3_shared24_cpu-132-021_8103_
        ;;
    tb4)
        eval_config="$server_dir/tb4_kimi_k3_shared24_miniswe.toml"
        approved_task_file="$workflow_dir/configs/eval/tb4_qwen_a95b_miniswe.tasks.txt"
        approved_task_file_sha256=9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892
        expected_config_sha256=aa5349078630181d574a55e15c23b487071f6d29cc77d2d79e92ced6003bcda6
        expected_rollout_cap=24
        expected_http_cap=24
        expected_waiting_cap=0
        dataset_archive=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/downloads/terminal-bench-prebuilt-v4.0.0.tar.gz
        dataset_archive_sha256=6d2c57cbcb1a75b5cdc0b0f989747fa68cdc65df8ff0a6893045a70ced7e668e
        dataset_content_sha256=564a42a4e2ce0a5efd23758656e4e419b3566a36234dfc09bae1029bc15326b2
        output_prefix=tb4_kimi_k3_shared24_cpu-132-021_8103_
        ;;
esac

require_private_artifact() {
    local configured=$1
    local label=$2
    local resolved owner mode digest
    if [[ -z "$configured" || "$configured" == *$'\n'* || "$configured" == *$'\t'* \
        || "$configured" != /* || -L "$configured" || ! -f "$configured" ]]; then
        printf '%s must be a canonical private regular file\n' "$label" >&2
        return 2
    fi
    resolved=$(realpath -e -- "$configured" 2>/dev/null || true)
    owner=$(stat -Lc '%u' -- "$configured" 2>/dev/null || true)
    mode=$(stat -Lc '%a' -- "$configured" 2>/dev/null || true)
    if [[ -z "$resolved" || "$resolved" != "$configured" || "$owner" != "$(id -u)" \
        || ! "$mode" =~ ^[0-7]{3,4}$ ]]; then
        printf '%s must be a canonical private regular file\n' "$label" >&2
        return 2
    fi
    if (( (8#$mode & 0077) != 0 )); then
        printf '%s must be a canonical private regular file\n' "$label" >&2
        return 2
    fi
    digest=$(sha256sum "$resolved" | cut -d' ' -f1)
    if [[ ! "$digest" =~ ^[0-9a-f]{64}$ ]]; then
        printf '%s could not be pinned\n' "$label" >&2
        return 2
    fi
    printf '%s\t%s\n' "$resolved" "$digest"
}

if [[ -z ${KIMI_SHARED_READINESS_CHECKPOINT:-} ]]; then
    printf 'KIMI_SHARED_READINESS_CHECKPOINT is required\n' >&2
    exit 2
fi
if [[ -z ${KIMI_SHARED_SMOKE_CHECKPOINT:-} ]]; then
    printf 'KIMI_SHARED_SMOKE_CHECKPOINT is required\n' >&2
    exit 2
fi
if ! readiness_metadata=$(
    require_private_artifact "$KIMI_SHARED_READINESS_CHECKPOINT" readiness_checkpoint
); then
    exit 2
fi
if ! smoke_metadata=$(
    require_private_artifact "$KIMI_SHARED_SMOKE_CHECKPOINT" smoke_checkpoint
); then
    exit 2
fi
IFS=$'\t' read -r readiness_checkpoint readiness_checkpoint_sha256 readiness_extra <<< "$readiness_metadata"
IFS=$'\t' read -r smoke_checkpoint smoke_checkpoint_sha256 smoke_extra <<< "$smoke_metadata"
if [[ -n "$readiness_extra" || -n "$smoke_extra" ]]; then
    printf 'Pinned checkpoint metadata is invalid\n' >&2
    exit 2
fi
promotion_certificate=
promotion_certificate_sha256=
if [[ "$profile" == mobius ]]; then
    if [[ -z ${KIMI_SHARED_PROMOTION_CERTIFICATE:-} ]]; then
        printf 'KIMI_SHARED_PROMOTION_CERTIFICATE is required for Mobius\n' >&2
        exit 2
    fi
    if ! promotion_metadata=$(
        require_private_artifact "$KIMI_SHARED_PROMOTION_CERTIFICATE" promotion_certificate
    ); then
        exit 2
    fi
    IFS=$'\t' read -r promotion_certificate promotion_certificate_sha256 promotion_extra \
        <<< "$promotion_metadata"
    if [[ -n "$promotion_extra" ]]; then
        printf 'Pinned promotion metadata is invalid\n' >&2
        exit 2
    fi
elif [[ -n ${KIMI_SHARED_PROMOTION_CERTIFICATE:-} ]]; then
    printf 'KIMI_SHARED_PROMOTION_CERTIFICATE is only valid for Mobius\n' >&2
    exit 2
fi

canonical_proxy_info="$deployment_root/proxy_info.json"
canonical_proxy_litellm_config="$deployment_root/proxy_litellm_config.yaml"
if [[ ! -r "$canonical_proxy_info" || ! -f "$canonical_proxy_info" || -L "$canonical_proxy_info" ]]; then
    printf 'The canonical shared Kimi proxy metadata is unavailable\n' >&2
    exit 2
fi
pinned_proxy_info_sha256=$(sha256sum "$canonical_proxy_info" | cut -d' ' -f1)
if [[ ! "$pinned_proxy_info_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'The canonical shared Kimi proxy metadata could not be pinned\n' >&2
    exit 2
fi

if [[ "$profile" == mobius ]]; then
    PYTHONPATH="$workflow_dir:$project_dir/environments/vmvm_tb_v2:$project_dir/deps/verifiers:$project_dir/deps/renderers:$project_dir/deps/pydantic-config/src:$x86_site${PYTHONPATH:+:$PYTHONPATH}" \
        "$x86_uv" run --no-project --offline --python "$python_bin" \
        python3 "$workflow_dir/mobius_launch_certificate.py" verify \
        "$promotion_certificate" \
        --certificate-sha256 "$promotion_certificate_sha256" \
        --production-config "$eval_config" \
        --approved-manifest "$approved_task_file" \
        --approved-manifest-sha256 "$approved_task_file_sha256" \
        --deployment-id "$deployment_id" \
        --deployment-spec "$deployment_spec" \
        --deployment-spec-sha256 "$deployment_spec_sha256" \
        --readiness-checkpoint "$readiness_checkpoint" \
        --readiness-checkpoint-sha256 "$readiness_checkpoint_sha256" \
        --capacity-smoke-checkpoint "$smoke_checkpoint" \
        --capacity-smoke-checkpoint-sha256 "$smoke_checkpoint_sha256" \
        --deployment-proxy-info "$canonical_proxy_info" \
        --deployment-proxy-info-sha256 "$pinned_proxy_info_sha256" \
        --requested-lease-start-concurrency 2 \
        >/dev/null
fi

validation_metadata=$(
    PYTHONPATH="$x86_site${PYTHONPATH:+:$PYTHONPATH}" \
        "$python_bin" "$server_dir/validate_launch.py" \
        --project-dir "$project_dir" \
        --deployment-root "$deployment_root" \
        --proxy-info "$canonical_proxy_info" \
        --eval-config "$eval_config" \
        --profile "$profile"
)
IFS=$'\t' read -r \
    proxy_info_sha256 route_count rollout_cap active_request_cap waiting_request_cap config_sha256 \
    proxy_litellm_config_sha256 metadata_extra \
    <<< "$validation_metadata"
if [[ ! "$proxy_info_sha256" =~ ^[0-9a-f]{64}$ \
    || "$route_count" != 24 \
    || "$rollout_cap" != "$expected_rollout_cap" \
    || "$active_request_cap" != "$expected_http_cap" \
    || "$waiting_request_cap" != "$expected_waiting_cap" \
    || "$config_sha256" != "$expected_config_sha256" \
    || ! "$proxy_litellm_config_sha256" =~ ^[0-9a-f]{64}$ \
    || ! -f "$canonical_proxy_litellm_config" \
    || -L "$canonical_proxy_litellm_config" \
    || "$(sha256sum "$canonical_proxy_litellm_config" | cut -d' ' -f1)" != "$proxy_litellm_config_sha256" \
    || -n "$metadata_extra" \
    || "$validation_metadata" == *$'\n'* \
    || "$pinned_proxy_info_sha256" != "$proxy_info_sha256" \
    || "$(sha256sum "$canonical_proxy_info" | cut -d' ' -f1)" != "$proxy_info_sha256" \
    || "$(sha256sum "$deployment_spec" | cut -d' ' -f1)" != "$deployment_spec_sha256" ]]; then
    printf 'The shared Kimi validator returned invalid metadata\n' >&2
    exit 2
fi
project_revision=$(git -C "$project_dir" rev-parse --verify HEAD)
if [[ ! "$project_revision" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'The shared Kimi source revision could not be pinned\n' >&2
    exit 2
fi

eval_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals
if [[ -L "$eval_root" || ! -d "$eval_root" || "$(realpath -e -- "$eval_root")" != "$eval_root" ]]; then
    printf 'The canonical evaluation root is unavailable or unsafe\n' >&2
    exit 2
fi
output_dir="$eval_root/$output_prefix$SLURM_JOB_ID"
if [[ -e "$output_dir" || -L "$output_dir" ]] || ! mkdir -m 700 -- "$output_dir"; then
    printf 'Fresh shared Kimi output already exists or cannot be created\n' >&2
    exit 2
fi
if [[ -L "$output_dir" || "$(realpath -e -- "$output_dir")" != "$output_dir" ]]; then
    printf 'Fresh shared Kimi output is not canonical\n' >&2
    exit 2
fi

export PROJECT_DIR="$project_dir"
export EVAL_RUN_ROLE="$profile"
export EVAL_DEPLOYMENT_ID="$deployment_id"
export EVAL_EXPECTED_MODEL=Kimi-K3
export EVAL_EXPECTED_PRIME_RL_REVISION="$project_revision"
export EVAL_CONFIG="$eval_config"
export EVAL_CONFIG_SHA256="$expected_config_sha256"
export EVAL_APPROVED_TASK_FILE="$approved_task_file"
export EVAL_APPROVED_TASK_FILE_SHA256="$approved_task_file_sha256"
export INFERENCE_DEPLOYMENT_SPEC="$deployment_spec"
export INFERENCE_DEPLOYMENT_SPEC_SHA256="$deployment_spec_sha256"
export INFERENCE_READINESS_CHECKPOINT="$readiness_checkpoint"
export INFERENCE_READINESS_CHECKPOINT_SHA256="$readiness_checkpoint_sha256"
export INFERENCE_SMOKE_CHECKPOINT="$smoke_checkpoint"
export INFERENCE_SMOKE_CHECKPOINT_SHA256="$smoke_checkpoint_sha256"
export INFERENCE_PROXY_INFO="$canonical_proxy_info"
export INFERENCE_PROXY_INFO_SHA256="$proxy_info_sha256"
export OUTPUT_DIR="$output_dir"
export VACLI_MAX_CONCURRENT_LEASES=2
if [[ "$profile" == mobius ]]; then
    export EVAL_DATASET_REVISION="$dataset_revision"
    export EVAL_PROMOTION_CERTIFICATE="$promotion_certificate"
    export EVAL_PROMOTION_CERTIFICATE_SHA256="$promotion_certificate_sha256"
else
    export EVAL_DATASET_ARCHIVE="$dataset_archive"
    export EVAL_DATASET_ARCHIVE_SHA256="$dataset_archive_sha256"
    export EVAL_DATASET_CONTENT_SHA256="$dataset_content_sha256"
fi

bash "$workflow_dir/run_eval.sbatch"
if [[ "$profile" == tb4 ]]; then
    RESULTS_DIR="$output_dir" \
    TB4_EXPECTED_ROLLOUT_CONCURRENCY=24 \
    TB4_EXPECTED_LEASE_START_CONCURRENCY=2 \
        bash "$workflow_dir/run_tb4_audit.sbatch"
fi
