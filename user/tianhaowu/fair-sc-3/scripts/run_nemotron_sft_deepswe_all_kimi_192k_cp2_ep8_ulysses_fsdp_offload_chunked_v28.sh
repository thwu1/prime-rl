#!/bin/bash
# Launch the isolated v28 192K CP2/Ulysses DeepSWE continuation with chunked loss and FSDP CPU offload.
# Optional arguments are forwarded as CLI overrides (for example, --dry-run).
set -euo pipefail
cd /storage/home/tianhaowu/prime-rl

# Keep Nemotron's Mamba dependencies isolated from the shared project environment.
export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export CUDA_HOME=/public/apps/cuda/12.6.1
export PATH="$CUDA_HOME/bin:$PATH"
# Models are pre-cached on shared storage; avoid the login-node proxy's HF 403.
export HF_HOME=/checkpoint/ram-h100-2/tianhaowu/.cache/huggingface
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"

CFG=/storage/home/tianhaowu/prime-rl/user/tianhaowu/fair-sc-3/configs/sft/nemotron_super_120b_deepswe_all_kimi_196608_cp2_ep8_ulysses_fsdp_offload_chunked_v28_8node_23steps.toml
exec uv run --no-sync sft @ "$CFG" "$@"
