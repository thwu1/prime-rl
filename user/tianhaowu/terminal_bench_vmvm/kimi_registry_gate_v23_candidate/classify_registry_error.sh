#!/usr/bin/bash -p

# Set REGISTRY_SAFE_CATEGORY from one private, owned diagnostic file. The raw
# diagnostic is never printed or copied. Phase and class must come from the same
# fixed worker line so explanatory prose cannot change a login into a pull.
classify_registry_error_file() {
    local error_file=$1 rc=$2 expected_identity=${3:-} observed_identity line phase= safe_class=
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
    elif /usr/bin/grep -q '^gate_category=podman_info$' "$error_file" 2>/dev/null; then
        REGISTRY_SAFE_CATEGORY=podman_info
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
        else
            REGISTRY_SAFE_CATEGORY=internal
        fi
    fi
    return 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    exit 2
fi
