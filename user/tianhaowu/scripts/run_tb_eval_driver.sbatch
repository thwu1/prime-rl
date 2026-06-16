#!/bin/bash
#SBATCH --job-name=tb-driver-v2
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=32
#SBATCH --mem=96G
#SBATCH --time=24:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/mn_eval_v2_driver.log
# Run the eval orchestrator on this dedicated cpu node. Override CFG/OUTDIR via
# --export if needed; defaults target the h200-v2 latest-infra run.
cd "$HOME/prime-rl"
echo "=== tb driver on cpu node $(hostname) $(date) ==="
# Scrub inherited SLURM allocation env: this driver runs as a SLURM job, so its
# SLURM_MEM_PER_NODE (from --mem) etc. would leak into the inference deployment
# we sbatch below (--export=ALL), making the deployments srun die on
# "SLURM_MEM_PER_CPU/GPU/NODE are mutually exclusive". Keep SLURM_CONF so sbatch
# can still find the cluster config.
for _v in $(compgen -v | grep "^SLURM_"); do [ "$_v" = SLURM_CONF ] && continue; unset "$_v"; done
exec bash user/tianhaowu/scripts/run_tb_eval_multinode_v2.sh
