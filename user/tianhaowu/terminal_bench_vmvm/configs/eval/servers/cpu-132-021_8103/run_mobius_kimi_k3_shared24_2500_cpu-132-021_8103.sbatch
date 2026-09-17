#!/bin/bash
#SBATCH --job-name=mobius-kimi-132021-8103
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=7-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/mobius_kimi_k3_shared24_cpu-132-021_8103_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/mobius_kimi_k3_shared24_cpu-132-021_8103_%j.log

set -euo pipefail

if (( $# != 0 )); then
    printf 'The shared Kimi launcher accepts no arguments or eval overrides\n' >&2
    exit 2
fi
if [[ -v KIMI_SHARED_WRITER_LOCK_FD ]]; then
    printf 'KIMI_SHARED_WRITER_LOCK_FD is reserved for the lock helper\n' >&2
    exit 2
fi
server_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
exec bash "$server_dir/launch_common.sh" mobius
