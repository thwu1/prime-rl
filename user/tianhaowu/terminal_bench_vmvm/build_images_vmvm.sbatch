#!/bin/bash
#SBATCH --job-name=tb-images
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --array=0-63%64
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/build_%A_%a.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/build_%A_%a.log

set -euo pipefail

project_dir=${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
build_plan=${BUILD_PLAN:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/build_plan.tsv}
slice_dir=${SLICE_DIR:-/checkpoint/ram/tianhaowu/terminal_bench_vmvm/build_slices}
mkdir -p "$slice_dir" /checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs

if [[ ! -f "$build_plan" ]]; then
    printf 'Missing BUILD_PLAN: %s\n' "$build_plan" >&2
    exit 2
fi
slice="$slice_dir/${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}.tsv"
awk -v worker="$SLURM_ARRAY_TASK_ID" -v workers="$SLURM_ARRAY_TASK_COUNT" \
    '((NR - 1) % workers) == worker' "$build_plan" > "$slice"
printf 'worker=%s/%s rows=%s\n' \
    "$SLURM_ARRAY_TASK_ID" "$SLURM_ARRAY_TASK_COUNT" "$(wc -l < "$slice")"

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export VACLI_LEASE_RETRIES=${VACLI_LEASE_RETRIES:-20}
exec bash "$project_dir/user/tianhaowu/terminal_bench_vmvm/build_images_vmvm.sh" "$slice"
