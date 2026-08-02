#!/bin/bash
#SBATCH --job-name=rsci-eval
#SBATCH --qos=h100_ram_high
#SBATCH --account=ram
#SBATCH --partition=h100
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:8
#SBATCH --cpus-per-task=64
#SBATCH --mem=256G
#SBATCH --time=04:00:00
#SBATCH --output=/checkpoint/ram-h100-2/tianhaowu/prime-rl-smoke/rsci_eval_%j.log

cd /storage/home/tianhaowu/prime-rl
CONFIG=${1:?usage: sbatch user/tianhaowu/rsci/scripts/run_eval.sbatch <eval-config.toml>}
exec bash user/tianhaowu/rsci/scripts/run_eval.sh "$CONFIG"
