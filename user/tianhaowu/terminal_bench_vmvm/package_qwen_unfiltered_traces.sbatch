#!/bin/bash
#SBATCH --job-name=qwen-trace-package
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=08:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_trace_package_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/qwen_trace_package_%j.log

set -euo pipefail
project=${QWEN_TRACE_PACKAGE_PROJECT_DIR:?}
exec bash "$project/user/tianhaowu/terminal_bench_vmvm/package_qwen_unfiltered_traces.sh"
