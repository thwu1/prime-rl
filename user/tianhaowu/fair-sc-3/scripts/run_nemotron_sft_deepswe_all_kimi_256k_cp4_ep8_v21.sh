#!/bin/bash
# Launch the isolated v21 DeepSWE all-Kimi continuation from v18 step 80.
# Optional arguments are forwarded as CLI overrides (for example, --dry-run).
set -euo pipefail
cd "$HOME/prime-rl"

# Keep Nemotron's Mamba dependencies isolated from the shared project environment.
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export CUDA_HOME=/public/apps/cuda/12.6.1
export PATH="$CUDA_HOME/bin:$PATH"
# Models are pre-cached on shared storage; avoid the login-node proxy's HF 403.
export HF_HOME=/checkpoint/ram-h100-2/tianhaowu/.cache/huggingface
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"

CFG=/storage/home/tianhaowu/prime-rl/user/tianhaowu/fair-sc-3/configs/sft/nemotron_super_120b_deepswe_all_kimi_262144_cp4_ep8_v21_8node_48steps.toml
exec uv run --no-sync sft @ "$CFG" "$@"
