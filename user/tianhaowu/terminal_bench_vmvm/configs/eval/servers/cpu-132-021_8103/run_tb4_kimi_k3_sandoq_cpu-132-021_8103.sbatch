#!/bin/bash
#SBATCH --job-name=k3-tb4-sandoq-8103
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=7-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_sandoq_8103_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_sandoq_8103_%j.log

set -euo pipefail
umask 077

if (( $# != 0 )); then
    printf 'Configure the Kimi Sandoq TB4 run through its sealed environment\n' >&2
    exit 2
fi

project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
server_dir="$workflow_dir/configs/eval/servers/cpu-132-021_8103"
expected_revision=${KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION:?Set KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION}
readiness_checkpoint=${KIMI_SANDOQ_READINESS_CHECKPOINT:?Set KIMI_SANDOQ_READINESS_CHECKPOINT}
stop_after_smoke=${KIMI_SANDOQ_STOP_AFTER_SMOKE:-0}

if [[ ! "$expected_revision" =~ ^[0-9a-f]{40}$ \
    || "$(git -C "$project_dir" rev-parse --verify HEAD)" != "$expected_revision" \
    || -n "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]]; then
    printf 'PROJECT_DIR must be the exact clean approved Kimi Sandoq source\n' >&2
    exit 2
fi
if [[ "$stop_after_smoke" != 0 && "$stop_after_smoke" != 1 ]]; then
    printf 'KIMI_SANDOQ_STOP_AFTER_SMOKE must be 0 or 1\n' >&2
    exit 2
fi
if [[ ! -f "$readiness_checkpoint" || -L "$readiness_checkpoint" \
    || "$(realpath -e -- "$readiness_checkpoint")" != "$readiness_checkpoint" ]]; then
    printf 'KIMI_SANDOQ_READINESS_CHECKPOINT must be a canonical regular file\n' >&2
    exit 2
fi

deployment_root=/checkpoint/ram/shared/vllm_deployments_v2/shared-kimi-k3
deployment_spec="$deployment_root/spec.yaml"
proxy_info="$deployment_root/proxy_info.json"
dataset_archive=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/downloads/terminal-bench-prebuilt-v4.0.0.tar.gz
smoke_config="$server_dir/tb4_kimi_k3_sandoq_smoke.toml"
full_config="$server_dir/tb4_kimi_k3_sandoq_pass1.toml"
smoke_task_file="$workflow_dir/configs/eval/tb4_kimi_token_smoke.tasks.txt"
full_task_file="$workflow_dir/configs/eval/tb4_qwen_a95b_miniswe.tasks.txt"
provider_profile="$server_dir/sandoq_use2.json"
eval_root=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals
smoke_output="$eval_root/tb4_kimi_k3_sandoq_cpu-132-021_8103_${SLURM_JOB_ID}_smoke"
full_output="$eval_root/tb4_kimi_k3_sandoq_cpu-132-021_8103_${SLURM_JOB_ID}_pass1"

for path in "$deployment_spec" "$proxy_info" "$dataset_archive" "$smoke_config" \
    "$full_config" "$smoke_task_file" "$full_task_file" "$provider_profile"; do
    if [[ ! -f "$path" || -L "$path" ]]; then
        printf 'Required Kimi Sandoq input is unavailable or unsafe\n' >&2
        exit 2
    fi
done
if [[ -e "$smoke_output" || -L "$smoke_output" || -e "$full_output" || -L "$full_output" ]]; then
    printf 'Kimi Sandoq output namespace is not fresh\n' >&2
    exit 2
fi

export PROJECT_DIR="$project_dir"
export EVAL_DEPLOYMENT_ID=shared-kimi-k3
export EVAL_EXPECTED_MODEL=Kimi-K3
export EVAL_EXPECTED_PRIME_RL_REVISION="$expected_revision"
export INFERENCE_DEPLOYMENT_SPEC="$deployment_spec"
export INFERENCE_DEPLOYMENT_SPEC_SHA256=ab00213a43083eba87f8b5999a3046e8d27ebe42b933ee845fd0cf4928b266e2
export INFERENCE_READINESS_CHECKPOINT="$readiness_checkpoint"
export INFERENCE_READINESS_CHECKPOINT_SHA256
INFERENCE_READINESS_CHECKPOINT_SHA256=$(sha256sum "$readiness_checkpoint" | awk '{print $1}')
export INFERENCE_PROXY_INFO="$proxy_info"
export INFERENCE_PROXY_INFO_SHA256
INFERENCE_PROXY_INFO_SHA256=$(sha256sum "$proxy_info" | awk '{print $1}')
export EVAL_DATASET_ARCHIVE="$dataset_archive"
export EVAL_DATASET_ARCHIVE_SHA256=6d2c57cbcb1a75b5cdc0b0f989747fa68cdc65df8ff0a6893045a70ced7e668e
export EVAL_DATASET_CONTENT_SHA256=564a42a4e2ce0a5efd23758656e4e419b3566a36234dfc09bae1029bc15326b2
export SANDOQ_PROVIDER_CONTEXT_PROFILE="$provider_profile"
export SANDOQ_PROVIDER_CONTEXT_PROFILE_SHA256=965511eb9578aa303d287491a7414e145241d6dbbf61469d13abbe801980a95a
unset EVAL_MODEL INFERENCE_BASE_URL INFERENCE_DEPLOYMENT_ID INFERENCE_JOB_ID INFERENCE_PROXY_URL
unset EVAL_PROMOTION_CERTIFICATE EVAL_PROMOTION_CERTIFICATE_SHA256 EVAL_DATASET_REVISION RESUME_DIR
unset INFERENCE_SMOKE_CHECKPOINT INFERENCE_SMOKE_CHECKPOINT_SHA256

export EVAL_RUN_ROLE=smoke
export EVAL_CONFIG="$smoke_config"
export EVAL_CONFIG_SHA256
EVAL_CONFIG_SHA256=$(sha256sum "$smoke_config" | awk '{print $1}')
export EVAL_APPROVED_TASK_FILE="$smoke_task_file"
export EVAL_APPROVED_TASK_FILE_SHA256=ecdcbc6e4f54b690e64b4566de5eecf33467088c8ca3436738cd7308d4e45b83
export OUTPUT_DIR="$smoke_output"
bash "$workflow_dir/run_eval.sbatch"

PROJECT_DIR="$project_dir" \
RESULTS_DIR="$smoke_output" \
SMOKE_TASK_FILE="$smoke_task_file" \
SMOKE_TASK_FILE_SHA256="$EVAL_APPROVED_TASK_FILE_SHA256" \
SMOKE_EXPECTED_TRACES=2 \
SMOKE_REQUIRE_EXACT_PROVIDER_JSON=1 \
    bash "$workflow_dir/run_trace_smoke_audit.sbatch"

smoke_checkpoint="$smoke_output/smoke_checkpoint.json"
if [[ ! -f "$smoke_checkpoint" || -L "$smoke_checkpoint" ]]; then
    printf 'Kimi Sandoq smoke did not publish its checkpoint\n' >&2
    exit 2
fi
if [[ "$stop_after_smoke" == 1 ]]; then
    printf 'Kimi Sandoq smoke completed; full TB4 intentionally deferred\n'
    exit 0
fi

export EVAL_RUN_ROLE=tb4
export EVAL_CONFIG="$full_config"
export EVAL_CONFIG_SHA256
EVAL_CONFIG_SHA256=$(sha256sum "$full_config" | awk '{print $1}')
export EVAL_APPROVED_TASK_FILE="$full_task_file"
export EVAL_APPROVED_TASK_FILE_SHA256=9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892
export OUTPUT_DIR="$full_output"
export INFERENCE_SMOKE_CHECKPOINT="$smoke_checkpoint"
export INFERENCE_SMOKE_CHECKPOINT_SHA256
INFERENCE_SMOKE_CHECKPOINT_SHA256=$(sha256sum "$smoke_checkpoint" | awk '{print $1}')
bash "$workflow_dir/run_eval.sbatch"

PROJECT_DIR="$project_dir" RESULTS_DIR="$full_output" \
    bash "$workflow_dir/run_tb4_audit.sbatch"
