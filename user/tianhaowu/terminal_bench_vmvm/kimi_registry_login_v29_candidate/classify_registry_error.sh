#!/usr/bin/bash -p

# Set REGISTRY_SAFE_CATEGORY from one private, owned diagnostic file. The raw
# diagnostic is never printed or copied. Phase and class must come from the same
# fixed worker line, and the dedicated guard contributes only fixed markers.
classify_registry_error_file() {
    local error_file=$1 rc=$2 expected_identity=${3:-} observed_identity line phase= safe_class=
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
    if /usr/bin/grep -q '^gate_category=private_cleanup_sensitive$' "$error_file" 2>/dev/null; then
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
    elif /usr/bin/grep -q '^gate_category=registry_login$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=registry_login
    elif /usr/bin/grep -Eq '^gate_guard_stage=(precondition|child|postcondition)$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=registry_login
    else
        while IFS= read -r line; do
            if [[ "$line" == *"private registry credential mint failed with category="* \
                || "$line" == *"private registry login failed with category="* \
                || "$line" == *"private registry login exhausted "*" with category="* ]]; then
                phase=login
            elif [[ "$line" == *"credential validation failed before login"* ]]; then
                phase=login
                safe_class=client-config
            else
                continue
            fi
            if [[ "$line" =~ category=([a-z][a-z-]*) ]]; then
                safe_class=${BASH_REMATCH[1]}
            fi
        done < "$error_file" 2>/dev/null
        if [[ "$phase" == login ]]; then
            case "$safe_class" in
                authentication|authorization|image|certificate|helper|client-config|local-storage|local-userns|local-lock|local-runtime|local-path|local-permission|credential-broker|empty-token|dns|timeout|eof|network|http|permanent)
                    REGISTRY_SAFE_CATEGORY=${phase}_${safe_class//-/_}
                    ;;
                *)
                    REGISTRY_SAFE_CATEGORY=registry_$phase
                    ;;
            esac
        elif (( rc == 130 || rc == 143 )); then
            REGISTRY_SAFE_CATEGORY=interrupted
        else
            REGISTRY_SAFE_CATEGORY=internal
        fi
    fi
    case "$REGISTRY_SAFE_CATEGORY" in
        podman_info_*|podman_store_*|login_*|registry_login)
            (( cleanup_proven == 1 )) || REGISTRY_SAFE_CATEGORY=private_cleanup_sensitive
            ;;
    esac
    return 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    exit 2
fi
