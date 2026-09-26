#!/usr/bin/bash -p
#SBATCH --job-name=k3-tb4-mswe-fcsmall
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_mswe_fcsmall_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/k3_tb4_mswe_fcsmall_%j.log

set +x
set -euo pipefail
umask 077

if (( $# != 0 )); then
    printf '{"code":"arguments_forbidden","state":"blocked"}\n' >&2
    exit 2
fi

project_dir=$(realpath -e -- "${PROJECT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}")
export PROJECT_DIR="$project_dir"
export KIMI_SMALL_CANARY_TASK_PROFILE=tb4
exec /usr/bin/bash -p \
    "$project_dir/user/tianhaowu/terminal_bench_vmvm/run_kimi_miniswe246_sandoq_small_canary.sbatch"
