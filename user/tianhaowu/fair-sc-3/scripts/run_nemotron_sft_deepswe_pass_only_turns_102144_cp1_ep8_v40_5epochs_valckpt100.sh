#!/bin/bash
# Launch the isolated v40 five-epoch assistant-turn-expanded DeepSWE run from Nemotron Super base.
set -euo pipefail
cd /storage/home/tianhaowu/prime-rl

NEMOTRON_VENV=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
test -x "$NEMOTRON_VENV/bin/python"
export UV_PROJECT_ENVIRONMENT="$NEMOTRON_VENV"
export CUDA_HOME=/public/apps/cuda/12.6.1
export PATH="$CUDA_HOME/bin:$PATH"
export HF_HOME=/checkpoint/ram-h100-2/tianhaowu/.cache/huggingface
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"

CFG=/storage/home/tianhaowu/prime-rl/user/tianhaowu/fair-sc-3/configs/sft/nemotron_super_120b_deepswe_pass_only_turns_102144_cp1_ep8_ulysses_fsdp_offload_expert_loop_fullmem_lr1e5_v40_8node_1346steps_5epochs_valckpt100.toml
exec env -u VIRTUAL_ENV uv run --no-sync sft @ "$CFG" "$@"
