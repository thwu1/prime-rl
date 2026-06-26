#!/bin/bash
#SBATCH --job-name=v1-e2e
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --output=/storage/home/tianhaowu/v1_e2e_%j.log
#SBATCH --error=/storage/home/tianhaowu/v1_e2e_%j.log

# Drives the real vmvm_tb_v1 backend through a simulated x2p drop + recovery.
# Runs in a fresh CPU job so the prolog provisions the x2pagentd sidecar vacli needs.
set -u
cd /storage/home/tianhaowu/prime-rl
export PYTHONPATH="/storage/home/tianhaowu/prime-rl/environments/vmvm_tb_v1${PYTHONPATH:+:$PYTHONPATH}"
echo "=== node=$(hostname) job=${SLURM_JOB_ID} X2P_PORT=${X2P_PORT:-unset} ==="
echo "=== which uv: $(command -v uv) ==="
uv run python /storage/home/tianhaowu/prime-rl/user/tianhaowu/fair-sc-3/scripts/_v1_e2e_test.py
echo "=== exit=$? ==="
