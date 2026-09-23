#!/bin/bash
#SBATCH --job-name=tb-ecr-build
#SBATCH --partition=cpu_x86
#SBATCH --qos=cpu_x86_lowest
#SBATCH --account=ram
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=12:00:00
#SBATCH --no-requeue
#SBATCH --output=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/ecr_build_%A_%a.log
#SBATCH --error=/checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs/ecr_build_%A_%a.log

set -euo pipefail
umask 077
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY='*'
export no_proxy='*'

plan=${1:?usage: sbatch build_images_ecr.sbatch BUILD_PLAN.tsv}
dataset_dir=${DATASET_DIR:?Set DATASET_DIR}
status_root=${BUILD_STATUS_ROOT:?Set BUILD_STATUS_ROOT}
expected_registry=588845226011.dkr.ecr.us-east-2.amazonaws.com
push_token_file=${ECR_PUSH_TOKEN_FILE:-}
array_index=${SLURM_ARRAY_TASK_ID:-0}
array_count=${SLURM_ARRAY_TASK_COUNT:-1}
build_proxy_port=${CPE_RUST_X2P_HTTP1_PROXY_PORT:-10054}
[[ "$build_proxy_port" =~ ^[1-9][0-9]{0,4}$ && "$build_proxy_port" -le 65535 ]] \
    || { printf 'Build proxy port is invalid\n' >&2; exit 2; }
build_proxy="http://127.0.0.1:$build_proxy_port"

[[ -f "$plan" && ! -L "$plan" ]] || { printf 'Build plan is unavailable\n' >&2; exit 2; }
dataset_dir=$(realpath -e -- "$dataset_dir")
install -d -m 700 "$status_root" /checkpoint/ram/tianhaowu/terminal_bench_vmvm/logs

storage_dir=$(mktemp -d /var/slurm-tmp/frontier-ecr-build.XXXXXX)
install -d -m 700 "$storage_dir/storage" "$storage_dir/run" "$storage_dir/run-xdg" "$storage_dir/docker-config"
export XDG_RUNTIME_DIR="$storage_dir/run-xdg"
export CONTAINERS_CONF="$storage_dir/containers.conf"
export DOCKER_CONFIG="$storage_dir/docker-config"
printf '[containers]\npidns = "host"\ndefault_sysctls = []\nkeyring = false\n' >"$CONTAINERS_CONF"
printf '{}\n' >"$DOCKER_CONFIG/config.json"
podman_storage=(
    /usr/bin/podman --storage-driver vfs
    --root "$storage_dir/storage" --runroot "$storage_dir/run"
)
cleanup() {
    "${podman_storage[@]}" system reset --force >/dev/null 2>&1 || true
    chmod -R u+rwX "$storage_dir" >/dev/null 2>&1 || true
    rm -rf -- "$storage_dir"
}
trap cleanup EXIT INT TERM

if [[ -n "$push_token_file" ]]; then
    [[ -f "$push_token_file" && ! -L "$push_token_file" \
        && "$(stat -c '%a:%u:%h' -- "$push_token_file")" == "600:$(id -u):1" ]] \
        || { printf 'ECR push token file is unavailable or unsafe\n' >&2; exit 2; }
    cp -- "$push_token_file" "$storage_dir/ecr-token"
else
    credential="/var/facebook/credentials/$USER/x509/$USER.pem"
    if [[ -f "$credential" ]]; then
        export THRIFT_TLS_CL_CERT_PATH="$credential"
        export THRIFT_TLS_CL_KEY_PATH="$credential"
    fi
    eval "$(ucloud aws get-credentials --role SSOContainerRegistryReadWrite 588845226011)"
    env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
        NO_PROXY='*' aws ecr get-login-password --region us-east-2 >"$storage_dir/ecr-token"
fi
"${podman_storage[@]}" login --username AWS --password-stdin "$expected_registry" <"$storage_dir/ecr-token" >/dev/null

selected=0
passed=0
failed=0
line_number=0
while IFS=$'\t' read -r task role context_sha256 context image extra; do
    [[ -n "$task" ]] || continue
    current=$line_number
    line_number=$((line_number + 1))
    (( current % array_count == array_index )) || continue
    selected=$((selected + 1))
    if [[ -n "$extra" || ! "$task" =~ ^[A-Za-z0-9._-]+$ \
        || ! "$role" =~ ^(agent|verifier)$ || ! "$context_sha256" =~ ^[0-9a-f]{64}$ \
        || "${image%%/*}" != "$expected_registry" ]]; then
        printf 'row=%d state=invalid\n' "$current"
        failed=$((failed + 1))
        continue
    fi
    context=$(realpath -e -- "$context")
    if [[ "$context" != "$dataset_dir"/* || ! -f "$context/Dockerfile" ]]; then
        printf 'row=%d state=invalid-context\n' "$current"
        failed=$((failed + 1))
        continue
    fi
    status="$status_root/${context_sha256}.${role}.json"
    if [[ -f "$status" ]] && jq -e --arg image "$image" \
        '.state == "success" and .image == $image and (.digest | test("^sha256:[0-9a-f]{64}$"))' \
        "$status" >/dev/null; then
        printf 'row=%d state=cached\n' "$current"
        passed=$((passed + 1))
        continue
    fi
    local_tag="localhost/frontier-${role}-${context_sha256:0:24}"
    digest_file="$storage_dir/digest-${current}"
    if "${podman_storage[@]}" build --network host --pull=missing \
        --build-arg "HTTP_PROXY=$build_proxy" --build-arg "HTTPS_PROXY=$build_proxy" \
        --build-arg "http_proxy=$build_proxy" --build-arg "https_proxy=$build_proxy" \
        --build-arg 'NO_PROXY=localhost,127.0.0.1' --build-arg 'no_proxy=localhost,127.0.0.1' \
        --tag "$local_tag" --file "$context/Dockerfile" "$context" >/dev/null \
        && "${podman_storage[@]}" tag "$local_tag" "$image" \
        && "${podman_storage[@]}" push --digestfile "$digest_file" "$image" >/dev/null; then
        digest=$(tr -d '\r\n' <"$digest_file")
        if [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
            temporary="$status.$$.tmp"
            jq -cn --arg task "$task" --arg role "$role" --arg context_sha256 "$context_sha256" \
                --arg image "$image" --arg digest "$digest" \
                '{state:"success",task:$task,role:$role,context_sha256:$context_sha256,image:$image,digest:$digest}' \
                >"$temporary"
            mv -f -- "$temporary" "$status"
            passed=$((passed + 1))
            printf 'row=%d state=success\n' "$current"
            continue
        fi
    fi
    failed=$((failed + 1))
    printf 'row=%d state=failed\n' "$current"
done <"$plan"

printf 'build_summary selected=%d passed=%d failed=%d\n' "$selected" "$passed" "$failed"
(( failed == 0 ))
