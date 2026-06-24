#!/bin/bash
#SBATCH --job-name=eval-12k-s30-driver
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=32
#SBATCH --mem=96G
#SBATCH --time=24:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/eval_12k_step30/driver_%j.log
cd "$HOME/prime-rl"
echo "=== eval 12k step30 driver on $(hostname) $(date) ==="
for _v in $(compgen -v | grep "^SLURM_"); do [ "$_v" = SLURM_CONF ] && continue; unset "$_v"; done
exec bash user/tianhaowu/fair-sc/scripts/run_eval_12k_step30.sh
