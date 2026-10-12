#!/bin/bash
#SBATCH --job-name=vmvm-probe
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --time=00:10:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/vmvm_probe_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/vmvm_probe_%j.log

set -euo pipefail
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

vacli=${VACLI_BIN:-/public/fbpkgs/x86_64/vacli/stable/vacli}
"$vacli" --x2p --faas-tenant-id "${VMVM_TENANT_ID:-async_2347641}" \
    lease --ttl 120s --ssh-cmd 'printf VMVM_CPU_OK' 2>&1 \
    | sed -E '/auth_token|paseto|token/d'
