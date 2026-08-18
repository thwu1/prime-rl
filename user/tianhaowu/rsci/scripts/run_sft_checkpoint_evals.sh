#!/bin/bash
set -euo pipefail

cd /storage/home/tianhaowu/prime-rl

RUN_DIR=/checkpoint/ram-h100-2/tianhaowu/rsci/sft/figure3-op11-14-200k-1epoch
for step in 62 124 186 248; do
  test -f "$RUN_DIR/weights/step_$step/STABLE"
  for panel in id_op2_10 ood_mid_op11_14; do
    config="user/tianhaowu/rsci/configs/eval/figure3_sft_op11_14_step${step}_${panel}.toml"
    output_dir=$(uv run python -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["eval"]["output_dir"])' "$config")
    if test -f "$output_dir/metrics.json"; then
      echo "already complete: $config"
      continue
    fi
    env -u SBATCH_OUTPUT -u SBATCH_ERROR \
      sbatch user/tianhaowu/rsci/scripts/run_eval.sbatch "$config"
  done
done
