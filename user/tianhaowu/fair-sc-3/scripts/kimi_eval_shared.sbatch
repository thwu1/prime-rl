#!/bin/bash
#SBATCH --job-name=kimi-eval-shared
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --cpus-per-task=64
#SBATCH --mem=240G
#SBATCH --time=120:00:00
#SBATCH --output=/checkpoint/ram/tianhaowu/kimi_eval_shared_%j.log
# CPU-node driver for the shared-router Kimi eval. The vacli VM sandbox can only be
# leased from a compute node, so this MUST run under SLURM (not the login node).
# Usage: sbatch kimi_eval_shared.sbatch <eval_config.toml>
cd "$HOME/prime-rl"
CFG=${1:?usage: sbatch kimi_eval_shared.sbatch <eval_config.toml>}
echo "=== kimi shared-router eval on $(hostname) $(date) | cfg=$CFG ==="
exec bash user/tianhaowu/fair-sc-3/scripts/run_kimi_eval_shared.sh "$CFG"
