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
info="/checkpoint/ram/shared/vllm_deployments_v2/$ID/proxy_info.json"
url=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['url'])" "$info")
model=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['model'])" "$info")
key=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['api_key'])" "$info")
key_file=/storage/home/tianhaowu/.config/ram-inference-gateway/$ID-token
(umask 077; printf '%s' "$key" >"$key_file")
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    NEMOTRON_TB4_BASE_URL="$url/v1" NEMOTRON_TB4_MODEL="$model" NEMOTRON_TB4_API_KEY_FILE="$key_file" \
    NEMOTRON_TB4_TASK_FILE="$(realpath -e "$TASKS")" NEMOTRON_TB4_RUN_NAME="$NAME" \
    NEMOTRON_TB4_ROLLOUTS="$ROLLOUTS" NEMOTRON_TB4_MAX_CONCURRENT="$CONCURRENT" \
    sbatch --parsable "$HERE/launch.sh"
