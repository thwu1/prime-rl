#!/bin/bash

set -euo pipefail

# Write the corrected ghenv.sh to /app/ghenv.sh
cat > /app/ghenv.sh << 'SOLEOF'
#!/bin/bash
#
# ghenv - GitHub Actions environment file format processor
# Implements the EnvFileKeyValuePairs format from the GitHub Actions runner.
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

        # FIX 3: Skip empty lines
        [ -z "$line" ] && continue

        local eq_pos heredoc_pos
        eq_pos=$(strpos "$line" "=")
        heredoc_pos=$(strpos "$line" "<<")

        local key="" value=""

        # FIX 1: Check precedence — whichever token appears first wins
        if [ "$eq_pos" -ge 0 ] && { [ "$heredoc_pos" -lt 0 ] || [ "$eq_pos" -lt "$heredoc_pos" ]; }; then
            # ---- Simple format: NAME=VALUE ----
            key="${line%%=*}"
            # FIX 4: Use # (shortest match) not ## (longest match)
            value="${line#*=}"

        elif [ "$heredoc_pos" -ge 0 ] && { [ "$eq_pos" -lt 0 ] || [ "$heredoc_pos" -lt "$eq_pos" ]; }; then
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
                # FIX 6: Check for EOF marker missing new line
                if [ -z "$NEWLINE" ]; then
                    die "Invalid value. EOF marker missing new line."
                fi
                # FIX 2: Subtract newline length from INDEX for end_idx
                end_idx=$(( INDEX - ${#NEWLINE} ))
            done

            if [ $found_delim -eq 0 ]; then
                die "Invalid value. Matching delimiter not found '${delimiter}'"
            fi

            if [ "$end_idx" -gt "$start_idx" ]; then
                value="${CONTENT:$start_idx:$((end_idx - start_idx))}"
            else
                value=""
            fi
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
            # FIX 5: Generate safe delimiter that doesn't appear as a line in value
            local delimiter="EOF"
            local counter=0
            while printf '%s\n' "$value" | grep -qFx "$delimiter"; do
                counter=$((counter + 1))
                delimiter="EOF_${counter}"
            done
            printf '%s<<%s\n' "$key" "$delimiter"
            printf '%s\n' "$value"
            printf '%s\n' "$delimiter"
        else
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

    CONTENT=$(<"$file")
    INDEX=0
    local errors=0
    local line_num=0

    while read_line; do
        line_num=$((line_num + 1))
        local line="$LINE"

        # Skip empty lines
        [ -z "$line" ] && continue

        local eq_pos heredoc_pos
        eq_pos=$(strpos "$line" "=")
        heredoc_pos=$(strpos "$line" "<<")

        if [ "$eq_pos" -ge 0 ] && { [ "$heredoc_pos" -lt 0 ] || [ "$eq_pos" -lt "$heredoc_pos" ]; }; then
            # Simple format — valid
            :
        elif [ "$heredoc_pos" -ge 0 ] && { [ "$eq_pos" -lt 0 ] || [ "$heredoc_pos" -lt "$eq_pos" ]; }; then
            # Heredoc format
            local hdr_line=$line_num
            local key="${line:0:$heredoc_pos}"
            local delimiter="${line:$((heredoc_pos + 2))}"

            if [ -z "$key" ]; then
                echo "line ${hdr_line}: Empty key in '${line}'" >&2
                errors=$((errors + 1))
                continue
            fi
            if [ -z "$delimiter" ]; then
                echo "line ${hdr_line}: Empty delimiter in '${line}'" >&2
                errors=$((errors + 1))
                continue
            fi

            local found_delim=0
            while read_line; do
                line_num=$((line_num + 1))
                if [ "$LINE" = "$delimiter" ]; then
                    found_delim=1
                    break
                fi
                if [ -z "$NEWLINE" ]; then
                    echo "line ${line_num}: EOF marker missing new line" >&2
                    errors=$((errors + 1))
                    found_delim=2
                    break
                fi
            done

            if [ $found_delim -eq 0 ]; then
                echo "line ${hdr_line}: Matching delimiter not found '${delimiter}'" >&2
                errors=$((errors + 1))
            fi
        else
            echo "line ${line_num}: Invalid format '${line}'" >&2
            errors=$((errors + 1))
        fi
    done

    if [ $errors -eq 0 ]; then
        echo "valid"
        return 0
    else
        return 1
    fi
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

    encode_pairs "$json_file" > "$tmpfile"
    parse_file "$tmpfile" > "${tmpfile}.parsed"

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
SOLEOF

chmod +x /app/ghenv.sh
