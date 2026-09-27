#!/usr/bin/bash -p
#SBATCH --job-name=k3-tb4-mswe-small-c24
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=7-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=48G
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@1800
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_mswe_small_c24_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_mswe_small_c24_%j.log

set +x
set -euo pipefail
umask 077

if (( $# != 0 )); then
    printf '{"code":"arguments_forbidden","state":"blocked"}\n' >&2
    exit 2
fi

project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
export PROJECT_DIR="$project_dir"
export KIMI_SANDOQ_STAGE=tb4-miniswe246-sandoq-small-full
export KIMI_SANDBOX_PROVIDER=sandoq
export KIMI_EXECUTION_MODE=small-firecracker-diagnostic
export KIMI_DIRECT_ROUTER_CAPACITY_PROFILE=sandoq-c64-w2-v1

: "${KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION:?Set KIMI_SANDOQ_EXPECTED_PRIME_RL_REVISION}"
: "${KIMI_TB4_SANDOQ_SMALL_PLAN:?Set KIMI_TB4_SANDOQ_SMALL_PLAN}"
: "${KIMI_TB4_SANDOQ_SMALL_PLAN_SHA256:?Set KIMI_TB4_SANDOQ_SMALL_PLAN_SHA256}"
: "${KIMI_SMALL_DEPLOYMENT_ROOT:?Set KIMI_SMALL_DEPLOYMENT_ROOT to a frozen generation with at least 96h remaining}"
export KIMI_DIRECT_DEPLOYMENT_ROOT="$KIMI_SMALL_DEPLOYMENT_ROOT"

exec /usr/bin/bash -p \
    "$project_dir/user/tianhaowu/terminal_bench_vmvm/configs/eval/servers/"\
"cpu-132-021_8103/run_tb4_kimi_k3_direct_sandoq_cpu-132-021_8103.sbatch"
