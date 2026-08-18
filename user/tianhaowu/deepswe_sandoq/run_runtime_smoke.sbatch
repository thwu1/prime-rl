#!/bin/bash
#SBATCH --job-name=deepswe-sandoq-smoke
#SBATCH --partition=cpu
#SBATCH --qos=cpu_lowest
#SBATCH --account=ram
#SBATCH --time=00:45:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=/checkpoint/ram/tianhaowu/deepswe_sandoq/logs/runtime_smoke_%j.log
#SBATCH --error=/checkpoint/ram/tianhaowu/deepswe_sandoq/logs/runtime_smoke_%j.log

set -euo pipefail

project_dir=/storage/home/tianhaowu/prime-rl
sandoq_site=/checkpoint/ram/tianhaowu/deepswe_eval/sandoq-client-site
mode=${1:-environment}

mkdir -p /checkpoint/ram/tianhaowu/deepswe_sandoq/logs
cd "$project_dir"

export UV_PROJECT_ENVIRONMENT=/storage/home/tianhaowu/.venvs/prime-rl-nemotron-sft
export UV_NO_SYNC=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$project_dir/user/tianhaowu/deepswe_modal:$project_dir/deps/sandoq-provider/extensions/sandoq:$sandoq_site${PYTHONPATH:+:$PYTHONPATH}"
export MODAL_DISABLE_API_PROXY=1
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy PRIME_API_KEY

if [ "$mode" = oci-runner ]; then
    export OCI_RUNNER_BASE_URL=https://sandoq.eks-prod.cf.aws.metafb.cloud
    export OCI_RUNNER_ENVIRONMENT=oci-runner
    export OCI_RUNNER_TOKEN_FILE=/home/tianhaowu/.config/oci-runner/token
    export OCI_RUNNER_OBSERVABILITY=1
    export OCI_RUNNER_SESSION_REUSE=0
fi

uv run --no-sync user/tianhaowu/deepswe_sandoq/smoke_runtime.py --mode "$mode"
