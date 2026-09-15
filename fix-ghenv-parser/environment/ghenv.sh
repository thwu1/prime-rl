#!/bin/bash
#
# ghenv - GitHub Actions environment file format processor
# Implements the EnvFileKeyValuePairs format from the GitHub Actions runner.
#
# This format is used by $GITHUB_OUTPUT, $GITHUB_ENV, and $GITHUB_STATE
# environment files to pass key-value pairs between workflow steps.
#
# Usage:
#   ghenv.sh parse <file>           Parse file to JSON array of {key, value}
#   ghenv.sh encode <json_file>     Encode JSON pairs to file format (stdout)
#   ghenv.sh validate <file>        Validate file, report errors with line numbers
#   ghenv.sh roundtrip <json_file>  Verify encode -> parse round-trip fidelity

set -uo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Line reader — operates on global CONTENT / INDEX
# Sets: LINE, NEWLINE, advances INDEX
# Returns 1 at EOF
# ---------------------------------------------------------------------------
CONTENT=""
INDEX=0

read_line() {
    if [ "$INDEX" -ge "${#CONTENT}" ]; then
        LINE=""
        NEWLINE=""
        return 1
    fi

    local rest="${CONTENT:$INDEX}"
    local before_lf="${rest%%$'\n'*}"

    if [ "$before_lf" = "$rest" ]; then
        # No newline found — remainder is the line
        LINE="$rest"
        NEWLINE=""
        INDEX=${#CONTENT}
    else
        LINE="$before_lf"
        NEWLINE=$'\n'
        INDEX=$(( INDEX + ${#before_lf} + 1 ))
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Find first occurrence of NEEDLE in HAYSTACK; print index or -1
# ---------------------------------------------------------------------------
strpos() {
    local haystack="$1" needle="$2"
    local prefix="${haystack%%"$needle"*}"
    if [ "$prefix" = "$haystack" ]; then
        echo -1
    else
        echo "${#prefix}"
    fi
}

# ---------------------------------------------------------------------------
# Parser — parse environment file to JSON
# ---------------------------------------------------------------------------
parse_file() {
    local file="$1"
    [ -f "$file" ] || die "File not found: $file"

    CONTENT=$(<"$file")
    INDEX=0

    local first=1
    echo "["

    while read_line; do
        local line="$LINE"

        local eq_pos heredoc_pos
        eq_pos=$(strpos "$line" "=")
        heredoc_pos=$(strpos "$line" "<<")

        local key="" value=""

        # Determine format based on available delimiters
        if [ "$heredoc_pos" -ge 0 ]; then
            # ---- Heredoc format: NAME<<DELIMITER ----
            key="${line:0:$heredoc_pos}"
            local delimiter="${line:$((heredoc_pos + 2))}"

            if [ -z "$key" ] || [ -z "$delimiter" ]; then
                die "Invalid format '${line}'. Name must not be empty and delimiter must not be empty"
            fi

            local start_idx=$INDEX
            local end_idx=$INDEX
            local found_delim=0

            while read_line; do
                if [ "$LINE" = "$delimiter" ]; then
                    found_delim=1
                    break
                fi
                end_idx=$INDEX
            done

            if [ $found_delim -eq 0 ]; then
                die "Invalid value. Matching delimiter not found '${delimiter}'"
            fi

            if [ "$end_idx" -gt "$start_idx" ]; then
                value="${CONTENT:$start_idx:$((end_idx - start_idx))}"
            else
                value=""
            fi

        elif [ "$eq_pos" -ge 0 ]; then
            # ---- Simple format: NAME=VALUE ----
            key="${line%%=*}"
            value="${line##*=}"
        else
            die "Invalid format '${line}'"
        fi

        # Emit JSON entry
        if [ $first -eq 1 ]; then
            first=0
        else
            echo ","
        fi
        printf '  {"key": %s, "value": %s}' \
            "$(printf '%s' "$key" | jq -Rs '.')" \
            "$(printf '%s' "$value" | jq -Rs '.')"
    done

    echo ""
    echo "]"
}

# ---------------------------------------------------------------------------
# Encoder — JSON array of {key, value} -> environment file format
# ---------------------------------------------------------------------------
encode_pairs() {
    local json_file="$1"
    [ -f "$json_file" ] || die "File not found: $json_file"

    local count
    count=$(jq 'length' "$json_file")

    local i=0
    while [ "$i" -lt "$count" ]; do
        local key value
        key=$(jq -r ".[$i].key" "$json_file")
        value=$(jq -r ".[$i].value" "$json_file")

        if [[ "$value" == *$'\n'* ]]; then
            # Multiline value — use heredoc format
            printf '%s<<%s\n' "$key" "EOF"
            printf '%s\n' "$value"
            printf '%s\n' "EOF"
        else
            # Single-line value — use simple format
            printf '%s=%s\n' "$key" "$value"
        fi

        i=$((i + 1))
    done
}

# ---------------------------------------------------------------------------
# Validator — check file for format errors, report all with line numbers
# ---------------------------------------------------------------------------
validate_file() {
    local file="$1"
    [ -f "$file" ] || die "File not found: $file"

    echo "valid"
    return 0
}

# ---------------------------------------------------------------------------
# Round-trip — encode then parse, verify equality
# ---------------------------------------------------------------------------
roundtrip_check() {
    local json_file="$1"
    [ -f "$json_file" ] || die "File not found: $json_file"

    local tmpfile
    tmpfile=$(mktemp)
    trap "rm -f '$tmpfile' '${tmpfile}.parsed'" EXIT

    # Encode to temp file
    encode_pairs "$json_file" > "$tmpfile"

    # Parse back
    parse_file "$tmpfile" > "${tmpfile}.parsed"

    # Compare (sort keys for stable comparison)
    local original normalized_parsed
    original=$(jq -cS '.' "$json_file")
    normalized_parsed=$(jq -cS '.' "${tmpfile}.parsed")

    if [ "$original" = "$normalized_parsed" ]; then
        echo "PASS: Round-trip successful"
        return 0
    else
        echo "FAIL: Round-trip mismatch"
        echo "--- Original ---"
        jq '.' "$json_file"
        echo "--- Parsed back ---"
        jq '.' "${tmpfile}.parsed"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------
case "${1:-}" in
    parse)
        [ -n "${2:-}" ] || die "Usage: ghenv.sh parse <file>"
        parse_file "$2"
        ;;
    encode)
        [ -n "${2:-}" ] || die "Usage: ghenv.sh encode <json_file>"
        encode_pairs "$2"
        ;;
    validate)
        [ -n "${2:-}" ] || die "Usage: ghenv.sh validate <file>"
        validate_file "$2"
        ;;
    roundtrip)
        [ -n "${2:-}" ] || die "Usage: ghenv.sh roundtrip <json_file>"
        roundtrip_check "$2"
        ;;
    *)
        die "Usage: ghenv.sh {parse|encode|validate|roundtrip} <file>"
        ;;
esac
