#!/bin/bash
#SBATCH --job-name=k3-tb4-gate
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_gate_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_gate_%j.log

set -euo pipefail
umask 077

if (( $# != 0 )); then
    printf 'Configure the Kimi TB4 gate through environment variables\n' >&2
    exit 2
fi

project_dir=${PROJECT_DIR:?Set PROJECT_DIR to the clean detached source snapshot}
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
deployment_id=${EVAL_DEPLOYMENT_ID:?Set EVAL_DEPLOYMENT_ID}
deployment_spec=${INFERENCE_DEPLOYMENT_SPEC:?Set INFERENCE_DEPLOYMENT_SPEC}
deployment_spec_sha256=${INFERENCE_DEPLOYMENT_SPEC_SHA256:?Set INFERENCE_DEPLOYMENT_SPEC_SHA256}
readiness_checkpoint=${INFERENCE_READINESS_CHECKPOINT:?Set INFERENCE_READINESS_CHECKPOINT}
proxy_info=${INFERENCE_PROXY_INFO:?Set INFERENCE_PROXY_INFO}
dataset_archive=${EVAL_DATASET_ARCHIVE:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/downloads/terminal-bench-prebuilt-v4.0.0.tar.gz}
dataset_archive_sha256=${EVAL_DATASET_ARCHIVE_SHA256:-6d2c57cbcb1a75b5cdc0b0f989747fa68cdc65df8ff0a6893045a70ced7e668e}
dataset_content_sha256=${EVAL_DATASET_CONTENT_SHA256:-564a42a4e2ce0a5efd23758656e4e419b3566a36234dfc09bae1029bc15326b2}
smoke_output_dir=${SMOKE_OUTPUT_DIR:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_sticky_smoke_1dc61931e_v1}
tb4_output_dir=${TB4_OUTPUT_DIR:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/evals/tb4_kimi_k3_sticky_full_1dc61931e_v1}
smoke_task_file="$workflow_dir/configs/eval/tb4_kimi_token_smoke.tasks.txt"
smoke_task_file_sha256=ecdcbc6e4f54b690e64b4566de5eecf33467088c8ca3436738cd7308d4e45b83
tb4_task_file="$workflow_dir/configs/eval/tb4_qwen_a95b_miniswe.tasks.txt"
tb4_task_file_sha256=9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892

if [[ "$(git -C "$project_dir" rev-parse HEAD)" != 1dc61931e9958733310cb5f351a1041f69ffd9bf \
    || -n "$(git -C "$project_dir" status --porcelain=v1 --untracked-files=all)" ]]; then
    printf 'PROJECT_DIR must be the clean approved Kimi evaluation snapshot\n' >&2
    exit 2
fi
if [[ ! -s "$readiness_checkpoint" ]]; then
    printf 'Missing completed readiness checkpoint\n' >&2
    exit 2
fi
readiness_checkpoint_sha256=$(sha256sum "$readiness_checkpoint" | cut -d' ' -f1)

unset EVAL_MODEL EVAL_PROMOTION_CERTIFICATE EVAL_PROMOTION_CERTIFICATE_SHA256
unset EVAL_DATASET_REVISION INFERENCE_BASE_URL INFERENCE_DEPLOYMENT_ID INFERENCE_JOB_ID
unset INFERENCE_PROXY_URL RESUME_DIR
export PROJECT_DIR="$project_dir"
export EVAL_DEPLOYMENT_ID="$deployment_id"
export EVAL_EXPECTED_MODEL=Kimi-K3
export EVAL_DATASET_ARCHIVE="$dataset_archive"
export EVAL_DATASET_ARCHIVE_SHA256="$dataset_archive_sha256"
export EVAL_DATASET_CONTENT_SHA256="$dataset_content_sha256"
export INFERENCE_DEPLOYMENT_SPEC="$deployment_spec"
export INFERENCE_DEPLOYMENT_SPEC_SHA256="$deployment_spec_sha256"
export INFERENCE_READINESS_CHECKPOINT="$readiness_checkpoint"
export INFERENCE_READINESS_CHECKPOINT_SHA256="$readiness_checkpoint_sha256"
export INFERENCE_PROXY_INFO="$proxy_info"
export VACLI_BIN=/public/fbpkgs/x86_64/vacli/stable/vacli
export VACLI_LEASE_RETRIES=20
export VACLI_MAX_CONCURRENT_LEASES=2
export VACLI_MAX_PULL_RETRIES=20
export VACLI_IMAGE_PULL_TIMEOUT_SECONDS=3600
export VACLI_CONTAINER_PRIVILEGED=1

export EVAL_RUN_ROLE=smoke
export EVAL_APPROVED_TASK_FILE="$smoke_task_file"
export EVAL_APPROVED_TASK_FILE_SHA256="$smoke_task_file_sha256"
export EVAL_CONFIG="$workflow_dir/configs/eval/tb4_kimi_k3_approved_smoke.toml"
export OUTPUT_DIR="$smoke_output_dir"
unset INFERENCE_SMOKE_CHECKPOINT INFERENCE_SMOKE_CHECKPOINT_SHA256
bash "$workflow_dir/run_eval.sbatch"

env \
    PROJECT_DIR="$project_dir" \
    RESULTS_DIR="$smoke_output_dir" \
    SMOKE_TASK_FILE="$smoke_task_file" \
    SMOKE_TASK_FILE_SHA256="$smoke_task_file_sha256" \
    SMOKE_EXPECTED_TRACES=2 \
    bash "$workflow_dir/run_trace_smoke_audit.sbatch"

smoke_checkpoint="$smoke_output_dir/smoke_checkpoint.json"
smoke_checkpoint_sha256=$(sha256sum "$smoke_checkpoint" | cut -d' ' -f1)
export EVAL_RUN_ROLE=tb4
export EVAL_APPROVED_TASK_FILE="$tb4_task_file"
export EVAL_APPROVED_TASK_FILE_SHA256="$tb4_task_file_sha256"
export EVAL_CONFIG="$workflow_dir/configs/eval/tb4_kimi_k3_max_miniswe.toml"
export OUTPUT_DIR="$tb4_output_dir"
export INFERENCE_SMOKE_CHECKPOINT="$smoke_checkpoint"
export INFERENCE_SMOKE_CHECKPOINT_SHA256="$smoke_checkpoint_sha256"
bash "$workflow_dir/run_eval.sbatch"

env \
    PROJECT_DIR="$project_dir" \
    RESULTS_DIR="$tb4_output_dir" \
    bash "$workflow_dir/run_tb4_audit.sbatch"
