#!/bin/bash
# Submit a TB4 Sandoq eval against a serve_api_v2 deployment.
# Usage: eval/run_eval.sh <deployment_id> <task_list> <run_name> [rollouts=1] [max_concurrent=16]
#   e.g. eval/run_eval.sh tianhaowu-nemotron-super-base-probe eval/tasks/trained19.tasks.txt base-trained19 4
set -euo pipefail
ID=${1:?deployment id}
TASKS=${2:?task list}
NAME=${3:?run name}
ROLLOUTS=${4:-1}
CONCURRENT=${5:-16}
HERE=$(cd "$(dirname "$0")" && pwd)
# Sandoq pulls task images with a 12h ECR token kept fresh by the login-node rotator (tmux session
# `ecr-rotation`, user/tianhaowu/terminal_bench_vmvm/sandoq_ecr_rotation.py rotate). An expired
# token makes every sandbox fail its startup with an opaque "Sandoq provisioning failed".
python3 - <<'EOF'
import json, time
state = json.load(open("/storage/home/tianhaowu/.config/oci-runner/ecr-rotation.state.json"))
hours = (state["expires_at_unix"] - time.time()) / 3600
if hours < 1:
    raise SystemExit(f"ECR token expires in {hours:.1f} h: restart the rotator (tmux session ecr-rotation) first")
EOF
info="/checkpoint/ram/shared/vllm_deployments_v2/$ID/proxy_info.json"
url=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['url'])" "$info")
model=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['model'])" "$info")
key=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['api_key'])" "$info")
# serve_api_v2 can start two proxies on one CPU node with the same port (both bind via SO_REUSEPORT);
# requests then reach whichever proxy accepts them, i.e. possibly the other deployment's model.
python3 - "$ID" <<'EOF'
import json, subprocess, sys
from pathlib import Path
target = sys.argv[1]
root = Path("/checkpoint/ram/shared/vllm_deployments_v2")
url = json.loads((root / target / "proxy_info.json").read_text())["url"]
clashes = []
for info in root.glob("*/proxy_info.json"):
    if info.parent.name == target:
        continue
    other = json.loads(info.read_text())
    if other.get("url") != url:
        continue
    alive = subprocess.run(["squeue", "-h", "-j", str(other.get("proxy_jobid", ""))], capture_output=True, text=True).stdout.strip()
    if alive:
        clashes.append(info.parent.name)
if clashes:
    raise SystemExit(f"{target} shares proxy {url} with live deployment(s) {clashes}; redeploy one of them first")
EOF
key_file=/storage/home/tianhaowu/.config/ram-inference-gateway/$ID-token
(umask 077; printf '%s' "$key" >"$key_file")
# The litellm proxy can report ready (or restart) before it accepts the model name; requests in that
# window fail with "Invalid model name" and the rollouts end ProviderError at turn 0.
for attempt in $(seq 1 30); do
    if env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy curl -sf -m 120 \
        -H "Authorization: Bearer $key" -H "Content-Type: application/json" "$url/v1/chat/completions" \
        -d "{\"model\": \"$model\", \"messages\": [{\"role\": \"user\", \"content\": \"hi\"}], \"max_tokens\": 4}" \
        >/dev/null; then
        break
    fi
    ((attempt < 30)) || { echo "$ID does not answer chat completions" >&2; exit 1; }
    sleep 30
done
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    NEMOTRON_TB4_BASE_URL="$url/v1" NEMOTRON_TB4_MODEL="$model" NEMOTRON_TB4_API_KEY_FILE="$key_file" \
    NEMOTRON_TB4_TASK_FILE="$(realpath -e "$TASKS")" NEMOTRON_TB4_RUN_NAME="$NAME" \
    NEMOTRON_TB4_ROLLOUTS="$ROLLOUTS" NEMOTRON_TB4_MAX_CONCURRENT="$CONCURRENT" \
    sbatch --parsable "$HERE/launch.sh"
