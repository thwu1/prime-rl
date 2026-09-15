#!/bin/bash
# runner-env.sh - CI Step Environment State Manager
# Processes GitHub Actions GITHUB_OUTPUT/GITHUB_ENV format with persistent
# storage (SQLite), integrity verification (HMAC), and concurrent-safe appends.
#
# Subcommands:
#   parse <envfile>                                - Parse env file to JSON
#   encode <jsonfile> <outfile>                    - Encode JSON to env file
#   validate <envfile>                             - Validate env file
#   init <dbpath>                                  - Initialize SQLite store
#   store <dbpath> <step-id> <envfile> <hmac-key>  - Store parsed entries
#   query <dbpath> <step-id> [key]                 - Query stored entries
#   verify <dbpath> <hmac-key>                     - Verify HMAC integrity
#   append <lockfile> <envfile> <key> <value>       - Atomic append via flock


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

init_store() {
    local db="$1"
    sqlite3 "$db" "CREATE TABLE IF NOT EXISTS outputs (step_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, hmac TEXT NOT NULL);"
}

store_entries() {
    local db="$1"
    local step_id="$2"
    local envfile="$3"
    local hmac_key="$4"

    local json
    json=$(parse_envfile "$envfile")
    local rc=$?
    if [[ $rc -ne 0 ]]; then
        return $rc
    fi

    local count
    count=$(printf '%s' "$json" | jq '. | length')

    local i
    for ((i = 0; i < count; i++)); do
        local key value hmac
        key=$(printf '%s' "$json" | jq -r ".[$i].key")
        value=$(printf '%s' "$json" | jq -r ".[$i].value")

        hmac=$(printf '%s' "$value" | openssl dgst -md5 -hmac "$hmac_key" 2>/dev/null | awk '{print $NF}')

        sqlite3 "$db" "INSERT INTO outputs VALUES ('$step_id', '$key', '$value', '$hmac');"
    done
}

query_entries() {
    local db="$1"
    local step_id="$2"
    local key="${3:-}"

    local query
    if [[ -n "$key" ]]; then
        query="SELECT key, value FROM outputs WHERE step_id='$step_id' AND key='$key';"
    else
        query="SELECT key, value FROM outputs WHERE step_id='$step_id';"
    fi

    local result='[]'
    while IFS='|' read -r k v; do
        result=$(printf '%s' "$result" | jq --arg k "$k" --arg v "$v" '. + [{"key": $k, "value": $v}]')
    done < <(sqlite3 "$db" "$query")

    printf '%s\n' "$result"
}

verify_chain() {
    local db="$1"
    local hmac_key="$2"

    while IFS='|' read -r sid skey svalue shmac; do
        local expected
        expected=$(printf '%s' "$svalue" | openssl dgst -md5 -hmac "$hmac_key" 2>/dev/null | awk '{print $NF}')
        if [[ "$expected" != "$shmac" ]]; then
            echo "Error: HMAC mismatch for step=$sid key=$skey" >&2
            return 1
        fi
    done < <(sqlite3 "$db" "SELECT step_id, key, value, hmac FROM outputs;")

    return 0
}

append_entry() {
    local lockfile="$1"
    local envfile="$2"
    local key="$3"
    local value="$4"

    flock -n "$lockfile" -c "
        if [[ \"$value\" == *\$'\\n'* ]]; then
            printf '%s\n' '${key}<<EOF' >> '$envfile'
            printf '%s\n' '$value' >> '$envfile'
            printf '%s\n' 'EOF' >> '$envfile'
        else
            printf '%s\n' '${key}=${value}' >> '$envfile'
        fi
    " || true
}

case "${1:-}" in
    parse)
        shift; parse_envfile "$@" ;;
    encode)
        shift; encode_envfile "$@" ;;
    validate)
        shift; validate_envfile "$@" ;;
    init)
        shift; init_store "$@" ;;
    store)
        shift; store_entries "$@" ;;
    query)
        shift; query_entries "$@" ;;
    verify)
        shift; verify_chain "$@" ;;
    append)
        shift; append_entry "$@" ;;
    *)
        echo "Usage: runner-env.sh {parse|encode|validate|init|store|query|verify|append} [args...]" >&2
        exit 1
        ;;
esac
