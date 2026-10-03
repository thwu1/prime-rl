#!/bin/bash
#SBATCH --job-name=k3-tb4-sq-fallback-8103
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=7-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=24G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_sandoq_fallback_8103_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_sandoq_fallback_8103_%j.log

set -euo pipefail
umask 077

if (( $# != 0 )); then
    printf 'Configure the sealed fallback lane through its environment\n' >&2
    exit 2
fi

case "${KIMI_SANDOQ_FALLBACK_LANE:?Set KIMI_SANDOQ_FALLBACK_LANE}" in
    memory_8g) fallback_stage=sandoq-fallback-memory-8g ;;
    memory_16g) fallback_stage=sandoq-fallback-memory-16g ;;
    *) printf 'KIMI_SANDOQ_FALLBACK_LANE is invalid\n' >&2; exit 2 ;;
esac

: "${KIMI_SANDOQ_FALLBACK_PLAN:?Set KIMI_SANDOQ_FALLBACK_PLAN}"
: "${KIMI_SANDOQ_FALLBACK_PLAN_SHA256:?Set KIMI_SANDOQ_FALLBACK_PLAN_SHA256}"
: "${KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION:?Set KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION}"

export KIMI_SANDOQ_STAGE="$fallback_stage"
export KIMI_SANDBOX_PROVIDER=sandoq
export KIMI_EXECUTION_MODE=sandoq-fallback-diagnostic
export KIMI_SANDOQ_PREFLIGHT_ONLY=0

project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
exec bash \
    "$project_dir/user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/cpu-132-021_8103/run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch"
