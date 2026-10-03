#!/usr/bin/bash -p

# Set REGISTRY_SAFE_CATEGORY from one private, owned diagnostic file. The raw
# diagnostic is never printed or copied. Phase and class must come from the same
# fixed worker line so explanatory prose cannot change a login into a pull.
classify_registry_error_file() {
    local error_file=$1 rc=$2 expected_identity=${3:-} observed_identity line phase= safe_class= last_stage=
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
    if /usr/bin/grep -q '^gate_category=allocation_identity$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=allocation_identity
    elif /usr/bin/grep -q '^gate_category=source_identity$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=source_identity
    elif /usr/bin/grep -q '^gate_category=compute_tools_identity$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=compute_tools_identity
    elif /usr/bin/grep -q '^gate_category=private_environment$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=private_environment
    elif /usr/bin/grep -q '^gate_category=podman_info_command$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_info_command
    elif /usr/bin/grep -q '^gate_category=podman_info_shape$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_info_shape
    elif /usr/bin/grep -q '^gate_category=podman_info_graphroot$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_info_graphroot
    elif /usr/bin/grep -q '^gate_category=podman_info_runroot$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_info_runroot
    elif /usr/bin/grep -q '^gate_category=podman_info_driver$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_info_driver
    elif /usr/bin/grep -q '^gate_category=podman_cold_present$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_cold_present
    elif /usr/bin/grep -q '^gate_category=podman_image_exists_command$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_image_exists_command
    elif /usr/bin/grep -q '^gate_category=registry_login_path$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=registry_login_path
    elif /usr/bin/grep -q '^gate_category=registry_login_open$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=registry_login_open
    elif /usr/bin/grep -q '^gate_category=registry_login_stat$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=registry_login_stat
    elif /usr/bin/grep -q '^gate_category=registry_login_identity$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=registry_login_identity
    elif /usr/bin/grep -q '^gate_category=image_identity$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=image_identity
    elif /usr/bin/grep -q '^gate_category=private_cleanup$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=private_cleanup
    else
        while IFS= read -r line; do
            case "$line" in
                gate_stage=probe_entry) last_stage=probe_entry ;;
                gate_stage=allocation_bound) last_stage=allocation_bound ;;
                gate_stage=declarations_bound) last_stage=declarations_bound ;;
                gate_stage=metadata_bound) last_stage=metadata_bound ;;
                gate_stage=descriptors_bound) last_stage=descriptors_bound ;;
                gate_stage=file_hashes_bound) last_stage=file_hashes_bound ;;
                gate_stage=manifest_bound) last_stage=manifest_bound ;;
                gate_stage=tools_bound) last_stage=tools_bound ;;
                gate_stage=tls_bound) last_stage=tls_bound ;;
                gate_stage=tls_fd_bound) last_stage=tls_fd_bound ;;
                gate_stage=source_bound) last_stage=source_bound ;;
                gate_stage=private_ready) last_stage=private_ready ;;
                gate_stage=podman_ready) last_stage=podman_ready ;;
                gate_stage=registry_enter) last_stage=registry_enter ;;
                gate_stage=worker_sourced) last_stage=worker_sourced ;;
                gate_stage=login_returned) last_stage=login_returned ;;
                gate_stage=auth_path_valid) last_stage=auth_path_valid ;;
                gate_stage=auth_opened) last_stage=auth_opened ;;
                gate_stage=auth_bound) last_stage=auth_bound ;;
                gate_stage=pull_returned) last_stage=pull_returned ;;
            esac
            if [[ "$line" == *"private registry credential mint failed with category="* \
                || "$line" == *"private registry login failed with category="* \
                || "$line" == *"private registry login exhausted "*" with category="* ]]; then
                phase=login
            elif [[ "$line" == *"container image pull failed with category="* \
                || "$line" == *"container image pull exhausted "*" with category="* ]]; then
                phase=pull
            elif [[ "$line" == *"credential validation failed before login"* ]]; then
                phase=login
                safe_class=client-config
            elif [[ "$line" == *"credential validation failed before pull"* ]]; then
                phase=pull
                safe_class=client-config
            else
                continue
            fi
            if [[ "$line" =~ category=([a-z][a-z-]*) ]]; then
                safe_class=${BASH_REMATCH[1]}
            fi
        done < "$error_file" 2>/dev/null
        if [[ "$phase" == login || "$phase" == pull ]]; then
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
        elif [[ -n "$last_stage" ]]; then
            REGISTRY_SAFE_CATEGORY=internal_after_${last_stage}
        else
            REGISTRY_SAFE_CATEGORY=internal
        fi
    fi
    return 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    exit 2
fi
