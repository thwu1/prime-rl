#!/bin/bash
#SBATCH --job-name=tb-kimi-shared
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=7-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/kimi_shared_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/kimi_shared_%j.log

set -euo pipefail
umask 077

if (( $# != 0 )); then
    printf 'The shared Kimi launcher accepts no arguments or eval overrides\n' >&2
    exit 2
fi

for forbidden in \
    DIRECT_QWEN_APPROVED_TASK_FILE \
    DIRECT_QWEN_APPROVED_TASK_FILE_SHA256 \
    EVAL_APPROVED_TASK_FILE \
    EVAL_APPROVED_TASK_FILE_SHA256 \
    EVAL_CONFIG \
    EVAL_MODEL \
    INFERENCE_BASE_URL \
    INFERENCE_DEPLOYMENT_ID \
    INFERENCE_JOB_ID \
    INFERENCE_PROXY_INFO \
    INFERENCE_PROXY_INFO_SHA256 \
    INFERENCE_PROXY_URL \
    OPENAI_API_KEY; do
    if [[ -n ${!forbidden:-} ]]; then
        printf '%s is forbidden for the pinned shared Kimi launcher\n' "$forbidden" >&2
        exit 2
    fi
done
if [[ -n ${VACLI_MAX_CONCURRENT_LEASES:-} && ${VACLI_MAX_CONCURRENT_LEASES} != 2 ]]; then
    printf 'VACLI_MAX_CONCURRENT_LEASES must be exactly 2 for shared Kimi\n' >&2
    exit 2
fi

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
server_dir="$workflow_dir/configs/eval/servers/cpu-132-021_8103"
eval_config="$server_dir/mobius_kimi_k3_shared24_2500.toml"
approved_task_file="$workflow_dir/configs/eval/mobius_valid_tasks_2500.txt"
approved_task_file_sha256=d33ef93f9b77ee91a41600934e677ba37988d3b4509e4da05ff1fcf7b4bc3a4b
deployment_root=/checkpoint/ram/shared/vllm_deployments_v2/shared-kimi-k3
canonical_proxy_info="$deployment_root/proxy_info.json"
python_bin=${PYTHON_BIN_X86_64:-python3}

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

validation_metadata=$(
    "$python_bin" "$server_dir/validate_launch.py" \
        --project-dir "$project_dir" \
        --deployment-root "$deployment_root" \
        --proxy-info "$proxy_snapshot" \
        --eval-config "$eval_config"
)
IFS=$'\t' read -r proxy_info_sha256 route_count active_request_cap waiting_request_cap metadata_extra \
    <<< "$validation_metadata"
if [[ ! "$proxy_info_sha256" =~ ^[0-9a-f]{64}$ \
    || "$route_count" != 24 \
    || "$active_request_cap" != 24 \
    || "$waiting_request_cap" != 40 \
    || -n "$metadata_extra" \
    || "$validation_metadata" == *$'\n'* \
    || "$(sha256sum "$proxy_snapshot" | cut -d' ' -f1)" != "$proxy_info_sha256" ]]; then
    printf 'The shared Kimi validator returned invalid metadata\n' >&2
    exit 2
fi

export PROJECT_DIR="$project_dir"
export EVAL_CONFIG="$eval_config"
export EVAL_APPROVED_TASK_FILE="$approved_task_file"
export EVAL_APPROVED_TASK_FILE_SHA256="$approved_task_file_sha256"
export INFERENCE_PROXY_INFO="$proxy_snapshot"
export INFERENCE_PROXY_INFO_SHA256="$proxy_info_sha256"
export VACLI_MAX_CONCURRENT_LEASES=2
export OUTPUT_DIR=${OUTPUT_DIR:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/mobius_kimi_shared24_${SLURM_JOB_ID}}

bash "$workflow_dir/run_eval.sbatch" &
eval_pid=$!
set +e
wait "$eval_pid"
status=$?
set -e
eval_pid=
exit "$status"
