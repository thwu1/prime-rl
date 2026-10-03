#!/bin/bash
# usage: launch.sh <run_name> [task_file]   (env MAX_CONCURRENT, RERUN_INVALID override)
set -euo pipefail
P=/storage/home/tianhaowu/prime-tb66-oracle
R=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/tb66_oracle_20260929
name=$1
tf=$(realpath "${2:-$R/tasks66.txt}")
cd "$P"
env PROJECT_DIR="$P" SANDBOX_PROVIDER=sandoq \
  DATASET_DIR=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/datasets/tb4-prebuilt-v4.0.0/tasks \
  IMAGE_PREFIX=vmvm-registry.fbinfra.net/terminal_bench IMAGE_TAG=tb4-452bf305c6da \
  USE_DECLARED_IMAGES=1 MAX_CONCURRENT=${MAX_CONCURRENT:-16} \
  INFRA_RETRIES=2 SETUP_TIMEOUT=3600 VALIDATE_TIMEOUT=${VALIDATE_TIMEOUT:-14400} SESSION_TIMEOUT=${SESSION_TIMEOUT:-14400} \
  MINIMUM_PASS_RATE=0.0 MINIMUM_VALID=0 ORACLE_SOLUTION_NETWORK_MODE=${NETMODE:-declared} \
  OUTPUT_DIR="$R/$name" RERUN_INVALID=${RERUN_INVALID:-1} \
  SANDBOX_CPU=4 SANDBOX_MEMORY_GB=7.7 SANDBOX_DISK_GB=57 \
  SANDOQ_TASK_NETWORK=${TASKNET:-host} \
  TASK_FILE="$tf" TASK_FILE_SHA256="$(sha256sum "$tf" | cut -d' ' -f1)" \
  sbatch --parsable --job-name=tb66-oracle-$name "$P/user/tianhaowu/terminal_bench_vmvm/run_oracle.sbatch"
