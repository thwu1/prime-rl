#!/bin/bash
# ghenv.sh - GitHub Actions Environment File Format Processor
# Implements parsing and encoding for GITHUB_OUTPUT/GITHUB_ENV format
#
# Usage:
#   ghenv.sh parse <envfile>           - Parse env file to JSON array
#   ghenv.sh encode <jsonfile> <out>   - Encode JSON pairs to env file
#   ghenv.sh validate <envfile>        - Validate env file format


set -uo pipefail

parse_envfile() {
    local file="$1"

    if [[ ! -f "$file" ]]; then
        echo '[]'
        return 0
    fi

    if [[ ! -s "$file" ]]; then
        echo '[]'
        return 0
    fi

    local result='[]'
    local in_heredoc=0
    local heredoc_key=""
    local heredoc_delim=""
    local heredoc_value=""

    while IFS= read -r line; do
        if [[ $in_heredoc -eq 1 ]]; then
            if [[ "$line" == "$heredoc_delim" ]]; then
                result=$(printf '%s' "$result" | jq \
                    --arg k "$heredoc_key" --arg v "$heredoc_value" \
                    '. + [{"key": $k, "value": $v}]')
                in_heredoc=0
                heredoc_key=""
                heredoc_delim=""
                heredoc_value=""
            else
                heredoc_value="${heredoc_value}
${line}"
            fi
            continue
        fi

        if [[ "$line" == *"="* ]]; then
            local key="${line%%=*}"
            local value="${line#*=}"
            if [[ -z "$key" ]]; then
                echo "Error: Empty key in line: $line" >&2
                return 1
            fi
            result=$(printf '%s' "$result" | jq \
                --arg k "$key" --arg v "$value" \
                '. + [{"key": $k, "value": $v}]')
        elif [[ "$line" == *"<<"* ]]; then
            local key="${line%%<<*}"
            local delim="${line#*<<}"
            if [[ -z "$key" || -z "$delim" ]]; then
                echo "Error: Invalid heredoc: empty key or delimiter" >&2
                return 1
            fi
            in_heredoc=1
            heredoc_key="$key"
            heredoc_delim="$delim"
            heredoc_value=""
        else
            echo "Error: Invalid format: $line" >&2
            return 1
        fi
    done < "$file"

    printf '%s\n' "$result"
    return 0
}

encode_envfile() {
    local json_file="$1"
    local output_file="$2"

    : > "$output_file"

    local count
    count=$(jq '. | length' "$json_file")

    local i
    for ((i = 0; i < count; i++)); do
        local key value
        key=$(jq -r ".[$i].key" "$json_file")
        value=$(jq -r ".[$i].value" "$json_file")

        if [[ "$value" == *$'\n'* ]]; then
            printf '%s\n' "${key}<<EOF" >> "$output_file"
            printf '%s\n' "$value" >> "$output_file"
            printf '%s\n' "EOF" >> "$output_file"
        else
            printf '%s\n' "${key}=${value}" >> "$output_file"
        fi
    done
}

validate_envfile() {
    local file="$1"

    if [[ ! -f "$file" ]]; then
        echo "Error: File not found: $file" >&2
        return 1
    fi

    parse_envfile "$file" > /dev/null 2>&1
    return $?
}

case "${1:-}" in
    parse)
        shift
        parse_envfile "$@"
        ;;
    encode)
        shift
        encode_envfile "$@"
        ;;
    validate)
        shift
        validate_envfile "$@"
        ;;
    *)
        echo "Usage: ghenv.sh {parse|encode|validate} [args...]" >&2
        exit 1
        ;;
esac
