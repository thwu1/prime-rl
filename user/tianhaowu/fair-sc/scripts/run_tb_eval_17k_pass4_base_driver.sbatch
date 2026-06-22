#!/bin/bash
#SBATCH --job-name=tb-17k-pass4-driver
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=32
#SBATCH --mem=96G
#SBATCH --time=120:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/tb_17k_pass4_driver.log
cd "$HOME/prime-rl"
echo "=== tb_v2 17k driver on cpu node $(hostname) $(date) ==="
for _v in $(compgen -v | grep "^SLURM_"); do [ "$_v" = SLURM_CONF ] && continue; unset "$_v"; done
exec bash user/tianhaowu/fair-sc/scripts/run_tb_eval_17k_pass4_base.sh
