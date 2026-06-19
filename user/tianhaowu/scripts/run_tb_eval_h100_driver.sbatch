#!/bin/bash
#SBATCH --job-name=tb-h100-driver
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=32
#SBATCH --mem=96G
#SBATCH --time=24:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/vmvm_tb_multinode_h100/driver_%j.log
cd "$HOME/prime-rl"
echo "=== tb h100 eval driver on cpu node $(hostname) $(date) ==="
for _v in $(compgen -v | grep "^SLURM_"); do [ "$_v" = SLURM_CONF ] && continue; unset "$_v"; done
exec bash user/tianhaowu/scripts/run_tb_eval_multinode_h100.sh
