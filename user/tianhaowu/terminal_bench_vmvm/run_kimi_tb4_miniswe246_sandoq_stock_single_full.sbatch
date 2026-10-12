#!/usr/bin/bash -p
#SBATCH --job-name=k3-tb4-stock-mswe-c24
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=6-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=48G
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@1800
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_stock_mswe_c24_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_stock_mswe_c24_%j.log

set +x
set -euo pipefail
umask 077

if (( $# != 0 )); then
    printf '{"code":"arguments_forbidden","state":"blocked"}\n' >&2
    exit 2
fi

project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
export PROJECT_DIR="$project_dir"
export KIMI_DIRECT_ROUTER_CAPACITY_PROFILE=sandoq-stock-single-c64-v1
export KIMI_SMALL_DEPLOYMENT_ROOT=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/private/kimi-k3-stock-single-1593665-20260927-v1
exec /usr/bin/bash -p \
    "$project_dir/user/tianhaowu/terminal_bench_vmvm/run_kimi_tb4_miniswe246_sandoq_small_full.sbatch"
