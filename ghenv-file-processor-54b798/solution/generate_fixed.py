#!/usr/bin/env python3
"""
Generate the corrected /app/runner-env.sh by programmatically constructing
the fixed bash script that addresses all bugs in the original.

Fixes applied:
 1. Parser: positional precedence of = vs << (was always checking = first)
 2. Parser: leading newline in heredoc values (no first-line tracking)
 3. Parser: empty lines not skipped (caused parse errors)
 4. Parser: missing || [[ -n "$line" ]] read guard (last line dropped)
 5. Parser: unterminated heredoc not detected (silent data loss)
 6. Encoder: hardcoded EOF delimiter (collision vulnerability)
 7. Encoder: command substitution strips trailing newlines from jq output
 8. Store/Verify: HMAC used md5 over value-only instead of sha256 over
    step_id:key:value
 9. Store: no escaping of single quotes causing SQL corruption
10. Query/Verify: pipe separator broke multiline values (switched to -json)
11. Append: flock -n (non-blocking) + || true silently dropped entries;
    values with quotes broke the -c command string

"""

import textwrap

FIXED_SCRIPT = textwrap.dedent(r'''
#!/bin/bash
# runner-env.sh - CI Step Environment State Manager (FIXED)
# Processes GitHub Actions GITHUB_OUTPUT/GITHUB_ENV format with persistent
# storage (SQLite), integrity verification (HMAC), and concurrent-safe appends.


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
    local first_value_line=1

    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ $in_heredoc -eq 1 ]]; then
            if [[ "$line" == "$heredoc_delim" ]]; then
                result=$(printf '%s' "$result" | jq \
                    --arg k "$heredoc_key" --arg v "$heredoc_value" \
                    '. + [{"key": $k, "value": $v}]')
                in_heredoc=0
                heredoc_key=""
                heredoc_delim=""
                heredoc_value=""
                first_value_line=1
            else
                if [[ $first_value_line -eq 1 ]]; then
                    heredoc_value="$line"
                    first_value_line=0
                else
                    heredoc_value="${heredoc_value}
${line}"
                fi
            fi
            continue
        fi

        if [[ -z "$line" ]]; then
            continue
        fi

        local eq_pos=-1
        local hd_pos=-1

        case "$line" in
            *=*)
                local _before="${line%%=*}"
                eq_pos=${#_before}
                ;;
        esac

        case "$line" in
            *"<<"*)
                local _before="${line%%<<*}"
                hd_pos=${#_before}
                ;;
        esac

        if [[ $eq_pos -ge 0 && ( $hd_pos -lt 0 || $eq_pos -lt $hd_pos ) ]]; then
            local key="${line%%=*}"
            local value="${line#*=}"
            if [[ -z "$key" ]]; then
                echo "Error: Empty key in line: $line" >&2
                return 1
            fi
            result=$(printf '%s' "$result" | jq \
                --arg k "$key" --arg v "$value" \
                '. + [{"key": $k, "value": $v}]')
        elif [[ $hd_pos -ge 0 && ( $eq_pos -lt 0 || $hd_pos -lt $eq_pos ) ]]; then
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
            first_value_line=1
        else
            echo "Error: Invalid format: $line" >&2
            return 1
        fi
    done < "$file"

    if [[ $in_heredoc -eq 1 ]]; then
        echo "Error: Unterminated heredoc, missing delimiter '$heredoc_delim'" >&2
        return 1
    fi

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
        key=$(jq -j ".[$i].key" "$json_file"; printf x)
        key="${key%x}"
        value=$(jq -j ".[$i].value" "$json_file"; printf x)
        value="${value%x}"

        if [[ "$value" == *$'\n'* ]]; then
            local delim="EOF"
            local suffix=0
            while printf '%s' "$value" | grep -qxF "$delim"; do
                suffix=$((suffix + 1))
                delim="EOF_${suffix}"
            done
            printf '%s\n' "${key}<<${delim}" >> "$output_file"
            printf '%s\n' "$value" >> "$output_file"
            printf '%s\n' "$delim" >> "$output_file"
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

        hmac=$(printf '%s' "${step_id}:${key}:${value}" | openssl dgst -sha256 -hmac "$hmac_key" 2>/dev/null | awk '{print $NF}')

        local esc_sid="${step_id//\'/\'\'}"
        local esc_key="${key//\'/\'\'}"
        local esc_value="${value//\'/\'\'}"
        local esc_hmac="${hmac//\'/\'\'}"
        sqlite3 "$db" "INSERT INTO outputs VALUES ('$esc_sid', '$esc_key', '$esc_value', '$esc_hmac');"
    done
}

query_entries() {
    local db="$1"
    local step_id="$2"
    local key="${3:-}"

    local esc_sid="${step_id//\'/\'\'}"
    local query
    if [[ -n "$key" ]]; then
        local esc_key="${key//\'/\'\'}"
        query="SELECT key, value FROM outputs WHERE step_id='$esc_sid' AND key='$esc_key';"
    else
        query="SELECT key, value FROM outputs WHERE step_id='$esc_sid';"
    fi

    local result
    result=$(sqlite3 -json "$db" "$query" 2>/dev/null)
    if [[ -z "$result" ]]; then
        echo '[]'
    else
        printf '%s\n' "$result"
    fi
}

verify_chain() {
    local db="$1"
    local hmac_key="$2"

    local all_rows
    all_rows=$(sqlite3 -json "$db" "SELECT step_id, key, value, hmac FROM outputs;" 2>/dev/null)
    if [[ -z "$all_rows" ]]; then
        return 0
    fi

    local count
    count=$(printf '%s' "$all_rows" | jq '. | length')

    local i
    for ((i = 0; i < count; i++)); do
        local sid skey svalue shmac expected
        sid=$(printf '%s' "$all_rows" | jq -r ".[$i].step_id")
        skey=$(printf '%s' "$all_rows" | jq -r ".[$i].key")
        svalue=$(printf '%s' "$all_rows" | jq -j ".[$i].value"; printf x)
        svalue="${svalue%x}"
        shmac=$(printf '%s' "$all_rows" | jq -r ".[$i].hmac")

        expected=$(printf '%s' "${sid}:${skey}:${svalue}" | openssl dgst -sha256 -hmac "$hmac_key" 2>/dev/null | awk '{print $NF}')
        if [[ "$expected" != "$shmac" ]]; then
            echo "Error: HMAC mismatch for step=$sid key=$skey" >&2
            return 1
        fi
    done

    return 0
}

append_entry() {
    local lockfile="$1"
    local envfile="$2"
    local key="$3"
    local value="$4"

    (
        flock 9
        if [[ "$value" == *$'\n'* ]]; then
            local delim="EOF"
            local suffix=0
            while printf '%s' "$value" | grep -qxF "$delim"; do
                suffix=$((suffix + 1))
                delim="EOF_${suffix}"
            done
            printf '%s\n' "${key}<<${delim}" >> "$envfile"
            printf '%s\n' "$value" >> "$envfile"
            printf '%s\n' "$delim" >> "$envfile"
        else
            printf '%s\n' "${key}=${value}" >> "$envfile"
        fi
    ) 9>"$lockfile"
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
''').lstrip()

with open("/app/runner-env.sh", "w") as f:
    f.write(FIXED_SCRIPT)

print("Fixed /app/runner-env.sh with all bug corrections.")
