#!/usr/bin/env bash
#SBATCH --job-name=rsci-rl-data-op11-20
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=/checkpoint/ram-h100-2/tianhaowu/prime-rl-smoke/rsci_rl_data_%j.log

set -euo pipefail
exec bash /storage/home/tianhaowu/prime-rl/user/tianhaowu/rsci/scripts/prepare_rl_op11_20.sh "$@"
