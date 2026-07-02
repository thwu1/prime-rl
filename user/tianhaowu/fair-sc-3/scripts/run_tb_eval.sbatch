#!/bin/bash
#SBATCH --job-name=tb-eval-driver-fsc3
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=32
#SBATCH --mem=96G
#SBATCH --time=48:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/tb_eval_driver_%j.log
# Generic CPU-node eval driver. Forwards its arg (the eval config) to run_tb_eval.sh, which
# submits the h200 inference deployment for the checkpoint and runs vf-eval against it.
#
# Launch:  sbatch user/tianhaowu/fair-sc-3/scripts/run_tb_eval.sbatch <eval_config.toml>
#   e.g.:  sbatch user/tianhaowu/fair-sc-3/scripts/run_tb_eval.sbatch \
#            user/tianhaowu/fair-sc-3/configs/eval/eval_ckpt175.toml
cd "$HOME/prime-rl"
CFG=${1:?usage: sbatch run_tb_eval.sbatch <eval_config.toml>}
echo "=== tb eval driver (fair-sc-3) on cpu node $(hostname) $(date) | config=$CFG ==="
# Drop inherited SLURM_* so the child inference `sbatch` renders a fresh h200 job (keep SLURM_CONF).
for _v in $(compgen -v | grep "^SLURM_"); do [ "$_v" = SLURM_CONF ] && continue; unset "$_v"; done
exec bash user/tianhaowu/fair-sc-3/scripts/run_tb_eval.sh "$CFG"
