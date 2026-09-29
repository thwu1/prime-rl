#!/bin/bash
# Serve a Nemotron-3-Super checkpoint (base or SFT HF dir) on one g3 node via ram_common's
# serve_api_v2, using the card in this folder. Prints the proxy URL when ready.
# Usage: serve/deploy.sh <deployment_id> <checkpoint_dir> [lifetime, default 24h]
set -euo pipefail
ID=${1:?deployment id, e.g. tianhaowu-nemotron-tb4-sft-262k}
CKPT=${2:?HF checkpoint dir}
LIFETIME=${3:-24h}
HERE=$(cd "$(dirname "$0")" && pwd)
SERVE=${SERVE_API_V2:-/storage/home/tianhaowu/ram_common-nemotron/vllm_tools/serve_api_v2}
card_dir="$SERVE/config/models/nemotron-3-super"
if ! cmp -s "$HERE/nemotron-3-super.card.toml" "$card_dir/card.toml" 2>/dev/null; then
    echo "installing card into $card_dir (not tracked by ram_common yet)"
    mkdir -p "$card_dir"
    cp "$HERE/nemotron-3-super.card.toml" "$card_dir/card.toml"
fi
cd "$SERVE"
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    ./serve.sh deploy "$ID" --model nemotron-3-super --endpoints 1 --checkpoint "$CKPT" \
    --set defaults.qos=g3_ram_high --lifetime "$LIFETIME"
cat "/checkpoint/ram/shared/vllm_deployments_v2/$ID/proxy_info.json"; echo
