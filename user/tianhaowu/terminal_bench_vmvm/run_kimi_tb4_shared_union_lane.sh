#!/usr/bin/env bash
set -euo pipefail
umask 077

blocked() {
    printf '{"code":"%s","state":"blocked"}\n' "$1" >&2
    exit 2
}

(( $# == 0 )) || blocked arguments_forbidden
project_dir=$(realpath -e -- "${PROJECT_DIR:?Set PROJECT_DIR}")
workflow_dir="$project_dir/user/tianhaowu/terminal_bench_vmvm"
ready_marker=${KIMI_SHARED_UNION_READY_MARKER:?Set KIMI_SHARED_UNION_READY_MARKER}
start_marker=${KIMI_SHARED_UNION_START_MARKER:?Set KIMI_SHARED_UNION_START_MARKER}
walltime_sha_file=${KIMI_SHARED_UNION_WALLTIME_SHA_FILE:?Set KIMI_SHARED_UNION_WALLTIME_SHA_FILE}
load_sha_file=${KIMI_SHARED_UNION_LOAD_GATE_SHA_FILE:?Set KIMI_SHARED_UNION_LOAD_GATE_SHA_FILE}
barrier_timeout=${KIMI_SHARED_UNION_BARRIER_TIMEOUT_SECONDS:-3600}

[[ "$ready_marker" == /* && "$start_marker" == /* \
    && "$ready_marker" != "$start_marker" \
    && "$barrier_timeout" =~ ^[1-9][0-9]*$ ]] \
    || blocked barrier_configuration_invalid
ready_parent=$(realpath -e -- "$(dirname -- "$ready_marker")")
start_parent=$(realpath -e -- "$(dirname -- "$start_marker")")
[[ "$ready_parent" == "$start_parent" \
    && "$(stat -c '%a:%u' -- "$ready_parent")" == "700:$(id -u)" \
    && ! -e "$ready_marker" && ! -L "$ready_marker" ]] \
    || blocked barrier_namespace_invalid

set -o noclobber
printf '{"state":"ready"}\n' >"$ready_marker"
set +o noclobber
chmod 0600 "$ready_marker"

deadline=$(( $(date +%s) + barrier_timeout ))
while [[ ! -f "$start_marker" || -L "$start_marker" ]]; do
    (( $(date +%s) < deadline )) || blocked barrier_timeout
    sleep 1
done
[[ "$(stat -c '%a:%h:%u' -- "$start_marker")" == "600:1:$(id -u)" \
    && "$(<"$start_marker")" == '{"state":"start"}' ]] \
    || blocked start_marker_invalid
for digest_file in "$walltime_sha_file" "$load_sha_file"; do
    [[ "$digest_file" == /* && -f "$digest_file" && ! -L "$digest_file" \
        && "$(stat -c '%a:%h:%u' -- "$digest_file")" == "600:1:$(id -u)" ]] \
        || blocked evidence_digest_file_invalid
done
walltime_sha256=$(<"$walltime_sha_file")
load_sha256=$(<"$load_sha_file")
[[ "$walltime_sha256" =~ ^[0-9a-f]{64}$ && "$load_sha256" =~ ^[0-9a-f]{64}$ ]] \
    || blocked evidence_digest_invalid
export DIRECT_KIMI_PRECAPTURED_ENDPOINT_WALLTIME_GATE_SHA256="$walltime_sha256"
export DIRECT_KIMI_PRECAPTURED_ENDPOINT_LOAD_GATE_SHA256="$load_sha256"

exec /usr/bin/bash -p "$workflow_dir/run_direct_kimi_sandoq_stage.sh"
