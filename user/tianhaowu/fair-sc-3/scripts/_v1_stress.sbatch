#!/bin/bash
#SBATCH --job-name=v1-stress
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=00:45:00
#SBATCH --nodes=1
#SBATCH --ntasks=1

# Extreme stress + drop-recovery test of vmvm_tb_v1 on a REAL terminal-bench task
# image. Runs in a fresh cpu job so the prolog provisions the x2pagentd sidecar.
# NOTE: the cluster forces job stdout to ~/log/slurm-<jobid>.out (the --output
# directive is ignored); `scontrol show job <id>` shows the real StdOut path.
set -u
cd /storage/home/tianhaowu/prime-rl
export PYTHONPATH="/storage/home/tianhaowu/prime-rl/environments/vmvm_tb_v1${PYTHONPATH:+:$PYTHONPATH}"
echo "=== node=$(hostname) job=${SLURM_JOB_ID} X2P_PROXY_URL=${X2P_PROXY_URL:-unset} ==="
uv run --no-sync python /storage/home/tianhaowu/prime-rl/user/tianhaowu/fair-sc-3/scripts/_v1_stress_test.py
echo "=== exit=$? ==="
