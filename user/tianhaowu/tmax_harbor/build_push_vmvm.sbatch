#!/bin/bash
#SBATCH --job-name=tmax-build
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=04:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --output=/checkpoint/ram/tianhaowu/tmax_build_logs/build_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/tmax_build_logs/build_%j.log

# Build TMax->harbor images on a leased VMVM VM and push to vmvm-registry.
# Runs on a cpu node (vacli cannot lease from the sandbox pod). TASK_FILE
# overridable via --export; defaults to the 10-task smoke list.
set -u
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export VACLI_LEASE_RETRIES=10 VACLI_MAX_PULL_RETRIES=12
exec bash /storage/home/tianhaowu/prime-rl/user/tianhaowu/tmax_harbor/build_push_vmvm.sh \
    "${TASK_FILE:-/checkpoint/ram/tianhaowu/tmax_smoke10.txt}"
