#!/bin/bash
set -euo pipefail
umask 077

if (( $# != 1 )) || [[ $1 != mobius && $1 != tb4 ]]; then
    printf 'The shared Kimi launch helper requires one pinned profile\n' >&2
    exit 2
fi
profile=$1
internal_writer_lock_fd=${KIMI_SHARED_WRITER_LOCK_FD:-}
if [[ -v KIMI_SHARED_WRITER_LOCK_FD && "$internal_writer_lock_fd" != 9 ]]; then
    printf 'KIMI_SHARED_WRITER_LOCK_FD is reserved for the lock helper\n' >&2
    exit 2
fi

for forbidden in \
    DIRECT_QWEN_APPROVED_TASK_FILE \
    DIRECT_QWEN_APPROVED_TASK_FILE_SHA256 \
    EVAL_APPROVED_TASK_FILE \
    EVAL_APPROVED_TASK_FILE_SHA256 \
    EVAL_CONFIG \
    EVAL_CONFIG_SHA256 \
    EVAL_DATASET_TREE_SHA256 \
    EVAL_MODEL \
    EVAL_WRITER_LOCK_FD \
    INFERENCE_BASE_URL \
    INFERENCE_DEPLOYMENT_ID \
    INFERENCE_JOB_ID \
    INFERENCE_PROXY_INFO \
    INFERENCE_PROXY_INFO_SHA256 \
    INFERENCE_PROXY_URL \
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
actual_server_dir=$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
if [[ "$actual_server_dir" != "$server_dir" ]]; then
    printf 'The shared Kimi helper must run from its pinned project tree\n' >&2
    exit 2
fi

case "$profile" in
    mobius)
        eval_config="$server_dir/mobius_kimi_k3_shared24_2500.toml"
        approved_task_file="$workflow_dir/configs/eval/mobius_valid_tasks_2500.txt"
        approved_task_file_sha256=d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b
        expected_config_sha256=cfe7891a16f175187d2e892f1293471a1626f3ebda33e9f3d9ae8aab223a7937
        expected_rollout_cap=64
        expected_http_cap=24
        expected_waiting_cap=40
        expected_dataset_tree_sha256=
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
        expected_dataset_tree_sha256=1a7ffccd2a221b43fa2f4a745fa6ae2e244c45282d5f5efa895aa902cfe79943
        output_prefix=tb4_kimi_k3_shared24_cpu-132-021_8103_
        ;;
esac

eval_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals
if [[ -L "$eval_root" || ! -d "$eval_root" || "$(realpath -e -- "$eval_root")" != "$eval_root" ]]; then
    printf 'The canonical evaluation root is unavailable or unsafe\n' >&2
    exit 2
fi

lane_resume_dir=
if [[ -v KIMI_SHARED_RESUME_DIR ]]; then
    if [[ -z "$KIMI_SHARED_RESUME_DIR" \
        || "$KIMI_SHARED_RESUME_DIR" != /* \
        || -L "$KIMI_SHARED_RESUME_DIR" ]]; then
        printf 'KIMI_SHARED_RESUME_DIR must be a canonical absolute lane directory\n' >&2
        exit 2
    fi
    lane_resume_dir=$(realpath -e -- "$KIMI_SHARED_RESUME_DIR" 2>/dev/null || true)
    resume_basename=${lane_resume_dir##*/}
    resume_parent=${lane_resume_dir%/*}
    resume_suffix=${resume_basename#"$output_prefix"}
    if [[ -z "$lane_resume_dir" \
        || "$lane_resume_dir" != "$KIMI_SHARED_RESUME_DIR" \
        || "$resume_parent" != "$eval_root" \
        || "$resume_basename" != "$output_prefix$resume_suffix" \
        || ! "$resume_suffix" =~ ^[1-9][0-9]*$ \
        || ! -d "$lane_resume_dir" ]]; then
        printf 'KIMI_SHARED_RESUME_DIR does not belong to this server/profile lane\n' >&2
        exit 2
    fi
    output_dir=$lane_resume_dir
else
    output_dir="$eval_root/$output_prefix$SLURM_JOB_ID"
    if [[ -z "$internal_writer_lock_fd" && ( -e "$output_dir" || -L "$output_dir" ) ]]; then
        printf 'Fresh shared Kimi output already exists; use KIMI_SHARED_RESUME_DIR\n' >&2
        exit 2
    fi
    if [[ -z "$internal_writer_lock_fd" ]]; then
        mkdir -m 700 -- "$output_dir"
    fi
    if [[ -L "$output_dir" || "$(realpath -e -- "$output_dir")" != "$output_dir" ]]; then
        printf 'Fresh shared Kimi output is not canonical\n' >&2
        exit 2
    fi
fi
output_owner=$(stat -Lc '%u' -- "$output_dir")
output_mode=$(stat -Lc '%a' -- "$output_dir")
if [[ "$output_owner" != "$(id -u)" ]] || (( (8#$output_mode & 0022) != 0 )); then
    printf 'The shared Kimi output must be owned by the launch user and not group/world writable\n' >&2
    exit 2
fi

writer_lock_path="$output_dir/.writer.lock"
if [[ -L "$writer_lock_path" ]]; then
    printf 'Refusing symlink writer lock: %s\n' "$writer_lock_path" >&2
    exit 2
fi
if [[ -z "$internal_writer_lock_fd" ]]; then
    exec "$python_bin" "$workflow_dir/open_writer_lock.py" \
        --lock-path "$writer_lock_path" \
        --env-var KIMI_SHARED_WRITER_LOCK_FD \
        -- bash "$server_dir/launch_common.sh" "$profile"
fi
exec 9>&"$internal_writer_lock_fd"
writer_lock_fd_path="/proc/$$/fd/9"
writer_lock_path_identity=$(stat -Lc '%d:%i' -- "$writer_lock_path" 2>/dev/null || true)
writer_lock_fd_identity=$(stat -Lc '%d:%i' -- "$writer_lock_fd_path" 2>/dev/null || true)
writer_lock_owner=$(stat -Lc '%u' -- "$writer_lock_fd_path" 2>/dev/null || true)
writer_lock_mode=$(stat -Lc '%a' -- "$writer_lock_fd_path" 2>/dev/null || true)
if [[ -L "$writer_lock_path" \
    || ! -f "$writer_lock_path" \
    || ! -f "$writer_lock_fd_path" \
    || -z "$writer_lock_path_identity" \
    || "$writer_lock_path_identity" != "$writer_lock_fd_identity" \
    || "$writer_lock_owner" != "$(id -u)" \
    || ! "$writer_lock_mode" =~ ^[0-7]{3,4}$ ]]; then
    printf 'Writer lock descriptor must reference the regular non-symlink lock path\n' >&2
    exit 2
fi
if (( (8#$writer_lock_mode & 0022) != 0 )); then
    printf 'Writer lock descriptor must reference the regular non-symlink lock path\n' >&2
    exit 2
fi
if ! flock -n 9; then
    printf 'Another evaluator owns %s\n' "$output_dir" >&2
    exit 2
fi
if [[ -L "$writer_lock_path" \
    || ! -f "$writer_lock_path" \
    || ! -f "$writer_lock_fd_path" \
    || "$(stat -Lc '%d:%i' -- "$writer_lock_path" 2>/dev/null || true)" != "$writer_lock_fd_identity" ]]; then
    printf 'Writer lock path changed while acquiring the lock\n' >&2
    exit 2
fi

deployment_root=/checkpoint/ram/shared/vllm_deployments_v2/shared-kimi-k3
canonical_proxy_info="$deployment_root/proxy_info.json"
runtime_dir=$(mktemp -d "${SLURM_TMPDIR:-/tmp}/tb-kimi-shared-${SLURM_JOB_ID:-local}.XXXXXX")
proxy_snapshot="$runtime_dir/proxy_info.json"
eval_pid=
cleanup() {
    status=$?
    trap - EXIT INT TERM
    if [[ -n "$eval_pid" ]] && kill -0 "$eval_pid" 2>/dev/null; then
        kill -TERM "$eval_pid" 2>/dev/null || true
        wait "$eval_pid" 2>/dev/null || true
    fi
    rm -rf -- "$runtime_dir"
    exit "$status"
}
trap cleanup EXIT INT TERM

if [[ ! -r "$canonical_proxy_info" ]]; then
    printf 'The canonical shared Kimi proxy_info.json is unavailable\n' >&2
    exit 2
fi
install -m 600 "$canonical_proxy_info" "$proxy_snapshot"

validation_args=(
    --project-dir "$project_dir"
    --deployment-root "$deployment_root"
    --proxy-info "$proxy_snapshot"
    --eval-config "$eval_config"
    --profile "$profile"
)
if [[ -n "$lane_resume_dir" ]]; then
    validation_args+=(--resume-dir "$lane_resume_dir")
fi
validation_metadata=$(
    "$python_bin" "$server_dir/validate_launch.py" "${validation_args[@]}"
)
IFS=$'\t' read -r \
    proxy_info_sha256 route_count rollout_cap active_request_cap waiting_request_cap config_sha256 metadata_extra \
    <<< "$validation_metadata"
if [[ ! "$proxy_info_sha256" =~ ^[0-9a-f]{64}$ \
    || "$route_count" != 24 \
    || "$rollout_cap" != "$expected_rollout_cap" \
    || "$active_request_cap" != "$expected_http_cap" \
    || "$waiting_request_cap" != "$expected_waiting_cap" \
    || "$config_sha256" != "$expected_config_sha256" \
    || -n "$metadata_extra" \
    || "$validation_metadata" == *$'\n'* \
    || "$(sha256sum "$proxy_snapshot" | cut -d' ' -f1)" != "$proxy_info_sha256" ]]; then
    printf 'The shared Kimi validator returned invalid metadata\n' >&2
    exit 2
fi

export PROJECT_DIR="$project_dir"
export EVAL_CONFIG="$eval_config"
export EVAL_CONFIG_SHA256="$expected_config_sha256"
export EVAL_APPROVED_TASK_FILE="$approved_task_file"
export EVAL_APPROVED_TASK_FILE_SHA256="$approved_task_file_sha256"
export INFERENCE_PROXY_INFO="$proxy_snapshot"
export INFERENCE_PROXY_INFO_SHA256="$proxy_info_sha256"
export EVAL_DATASET_TREE_SHA256="$expected_dataset_tree_sha256"
export EVAL_WRITER_LOCK_FD=9
export VACLI_MAX_CONCURRENT_LEASES=2
unset KIMI_SHARED_RESUME_DIR
unset KIMI_SHARED_WRITER_LOCK_FD
if [[ -n "$lane_resume_dir" ]]; then
    RESUME_DIR=$lane_resume_dir
    export RESUME_DIR
else
    export OUTPUT_DIR="$output_dir"
fi

bash "$workflow_dir/run_eval.sbatch" &
eval_pid=$!
set +e
wait "$eval_pid"
status=$?
set -e
eval_pid=
exit "$status"
