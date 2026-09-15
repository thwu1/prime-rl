#!/usr/bin/env bash
#
# Recursively resolves $(path/to/file.json) include references
# in MASSim configuration files using jq + bash.

resolve() {
    local file="$1"
    local dir
    dir="$(cd "$(dirname "$file")" && pwd)"
    local json
    json="$(cat "$file")"

    while true; do
        # Find the first $(path) string reference in the JSON
        local ref
        ref=$(echo "$json" | jq -r '
            [.. | strings | select(startswith("$(") and endswith(")"))]
            | if length == 0 then "" else .[0] end
        ')

        # No more references — done
        if [ -z "$ref" ]; then
            break
        fi

        # Extract the file path from $(path)
        local path="${ref:2:${#ref}-3}"
        local ref_file="$dir/$path"

        # Recursively resolve the referenced file
        local resolved
        resolved=$(resolve "$ref_file")

        # Replace the string value with the resolved JSON content
        json=$(echo "$json" | jq --arg pat "$ref" --argjson val "$resolved" \
            'walk(if type == "string" and . == $pat then $val else . end)')
    done

    echo "$json"
}

resolve /app/conf/config.json | jq . > /app/resolved_config.json
