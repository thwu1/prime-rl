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
# Trainer checkpoints keep the base config's auto_map but (before the save_metadata fix) not the
# remote-code files it names; vLLM with trust_remote_code then refuses to load them.
BASE_MODEL=${BASE_MODEL:-/checkpoint/ram/tianhaowu/models/NVIDIA-Nemotron-3-Super-120B-A12B-BF16}
python3 - "$CKPT" "$BASE_MODEL" <<'PY'
import json, shutil, sys
from pathlib import Path
ckpt, base = Path(sys.argv[1]), Path(sys.argv[2])
auto_map = json.loads((ckpt / "config.json").read_text()).get("auto_map", {})
for ref in {v.split(".")[0] for v in auto_map.values() if isinstance(v, str)}:
    name = f"{ref.split('--')[-1]}.py"
    if not (ckpt / name).exists():
        shutil.copy2(base / name, ckpt / name)
        print(f"copied {name} from {base}")
PY
cd "$SERVE"
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    ./serve.sh deploy "$ID" --model nemotron-3-super --endpoints 1 --checkpoint "$CKPT" \
    --set defaults.qos=g3_ram_high --lifetime "$LIFETIME"
cat "/checkpoint/ram/shared/vllm_deployments_v2/$ID/proxy_info.json"; echo
