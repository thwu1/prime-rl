#!/usr/bin/bash -p

# Set REGISTRY_SAFE_CATEGORY from one private, owned diagnostic file. The raw
# diagnostic is never printed or copied. Operational causes are accepted only
# from the gate's closed fixed-marker allowlist; arbitrary worker prose is ignored.
classify_registry_error_file() {
    local error_file=$1 rc=$2 expected_identity=${3:-} observed_identity line marker= marker_count=0
    local cleanup_proof_count=0 cleanup_proven=0
    REGISTRY_SAFE_CATEGORY=
    [[ "$error_file" == /* ]] || return 1
    if [[ -n "$expected_identity" ]]; then
        [[ "$error_file" =~ ^/proc/self/fd/[1-9][0-9]*$ && -f "$error_file" ]] || return 1
        observed_identity=$(/usr/bin/stat -Lc '%d:%i:%a:%u:%h' -- "$error_file" 2>/dev/null) \
            || return 1
        [[ "$observed_identity" == "$expected_identity" \
            && "$observed_identity" == *':600:656177:1' ]] || return 1
    else
        [[ -f "$error_file" && ! -L "$error_file" \
            && "$(/usr/bin/stat -c '%a:%u:%h' -- "$error_file" 2>/dev/null)" == '600:656177:1' ]] \
            || return 1
    fi
    cleanup_proof_count=$(/usr/bin/grep -Fxc 'gate_cleanup=retained_empty' "$error_file" 2>/dev/null || true)
    if [[ "$cleanup_proof_count" == 1 ]]; then
        cleanup_proven=1
    fi
    if /usr/bin/grep -q '^gate_category=live_writer_cleanup_unproven$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=live_writer_cleanup_unproven
    elif /usr/bin/grep -q '^gate_category=private_cleanup_sensitive$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=private_cleanup_sensitive
    elif /usr/bin/grep -q '^gate_category=private_cleanup_retained$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=private_cleanup_retained
    elif /usr/bin/grep -q '^gate_category=private_cleanup$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=private_cleanup
    elif /usr/bin/grep -q '^gate_category=allocation_identity$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=allocation_identity
    elif /usr/bin/grep -q '^gate_category=probe_source_identity$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=probe_source_identity
    elif /usr/bin/grep -q '^gate_category=private_environment$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=private_environment
    elif /usr/bin/grep -q '^gate_category=podman_info_command$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_info_command
    elif /usr/bin/grep -q '^gate_category=podman_info_shape$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_info_shape
    elif /usr/bin/grep -q '^gate_category=podman_store_graphroot$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_store_graphroot
    elif /usr/bin/grep -q '^gate_category=podman_store_runroot$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_store_runroot
    elif /usr/bin/grep -q '^gate_category=podman_store_driver$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_store_driver
    elif /usr/bin/grep -q '^gate_category=podman_info_image_present$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_info_image_present
    elif /usr/bin/grep -q '^gate_category=podman_info_image_check$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_info_image_check
    elif /usr/bin/grep -q '^gate_category=registry_pull$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=registry_pull
    elif /usr/bin/grep -Eq '^gate_guard_stage=(precondition|child|postcondition)$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=registry_pull
    else
        while IFS= read -r line; do
            [[ "$line" == gate_category=* ]] || continue
            marker=${line#gate_category=}
            case "$marker" in
                pull_mint_broker|pull_mint_timeout|pull_mint_empty|pull_token_shape|\
                pull_authfile_create|pull_authfile_lookup|pull_guard_precondition|\
                pull_guard_child|pull_guard_postcondition|pull_http_400|pull_http_401|\
                pull_http_403|pull_http_404|pull_http_other4xx|pull_http_5xx|pull_expired|\
                pull_not_authorized|pull_denied|pull_auth_challenge|pull_config|pull_writeback|\
                pull_tls|pull_proxy|pull_transport|pull_timeout|pull_image_missing|pull_platform|\
                pull_storage|pull_empty_125|pull_empty_other|pull_unknown|\
                image_identity|image_remove)
                    REGISTRY_SAFE_CATEGORY=$marker
                    marker_count=$((marker_count + 1))
                    ;;
            esac
        done < "$error_file" 2>/dev/null
        if (( marker_count != 1 )); then
            REGISTRY_SAFE_CATEGORY=
        fi
        if [[ -n "$REGISTRY_SAFE_CATEGORY" ]]; then
            :
        elif (( rc == 130 || rc == 143 )); then
            REGISTRY_SAFE_CATEGORY=interrupted
        else
            REGISTRY_SAFE_CATEGORY=internal
        fi
    fi
    case "$REGISTRY_SAFE_CATEGORY" in
        podman_info_*|podman_store_*|pull_*|registry_pull|image_identity|image_remove)
            (( cleanup_proven == 1 )) || REGISTRY_SAFE_CATEGORY=private_cleanup_sensitive
            ;;
    esac
    return 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    exit 2
fi
