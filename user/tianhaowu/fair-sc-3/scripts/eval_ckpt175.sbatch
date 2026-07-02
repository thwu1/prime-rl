#!/bin/bash
#SBATCH --job-name=eval-ckpt175-driver-fsc3
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=32
#SBATCH --mem=96G
#SBATCH --time=48:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/eval_ckpt175_driver_fsc3.log
# CPU-node driver: submits the h200 inference deployment for the ckpt and runs vf-eval against it.
cd "$HOME/prime-rl"
echo "=== eval ckpt175 driver (fair-sc-3) on cpu node $(hostname) $(date) ==="
# Drop inherited SLURM_* so the child inference `sbatch` renders a fresh h200 job (keep SLURM_CONF).
for _v in $(compgen -v | grep "^SLURM_"); do [ "$_v" = SLURM_CONF ] && continue; unset "$_v"; done
exec bash user/tianhaowu/fair-sc-3/scripts/run_tb_eval.sh \
  user/tianhaowu/fair-sc-3/configs/eval_ckpt175.toml
