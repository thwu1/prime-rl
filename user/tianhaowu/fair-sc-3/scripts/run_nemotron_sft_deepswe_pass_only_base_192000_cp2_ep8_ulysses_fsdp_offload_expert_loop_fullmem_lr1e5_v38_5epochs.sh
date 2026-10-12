#!/bin/bash
# Launch the isolated v38 five-epoch 192000-token CP2/Ulysses pass-only DeepSWE run from Nemotron Super base.
# Optional arguments are forwarded as CLI overrides (for example, --dry-run).
set -euo pipefail
cd /storage/home/tianhaowu/prime-rl

# Keep Nemotron's Mamba dependencies isolated from the shared project environment.
NEMOTRON_VENV=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
test -x "$NEMOTRON_VENV/bin/python"
export UV_PROJECT_ENVIRONMENT="$NEMOTRON_VENV"
export CUDA_HOME=/public/apps/cuda/12.6.1
export PATH="$CUDA_HOME/bin:$PATH"
# Models are pre-cached on shared storage; avoid the login-node proxy's HF 403.
export HF_HOME=/checkpoint/ram-h100-2/tianhaowu/.cache/huggingface
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"

CFG=/storage/home/tianhaowu/prime-rl/user/tianhaowu/fair-sc-3/configs/sft/nemotron_super_120b_deepswe_pass_only_base_192000_cp2_ep8_ulysses_fsdp_offload_expert_loop_fullmem_lr1e5_v38_8node_57steps_5epochs.toml
exec env -u VIRTUAL_ENV uv run --no-sync sft @ "$CFG" "$@"
