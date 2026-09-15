#!/bin/bash
# Extract per-package variable overrides from a package_*() function.
# Usage: extract_func.sh <pkgbuild_directory> <function_name>
# Output: tab-separated lines (same format as extract_globals.sh)
#   Only outputs variables explicitly set in the function body.

set -e
PKGDIR="$1"
FUNC_NAME="$2"

cd "$PKGDIR"
source PKGBUILD

# Get function body
func_body=$(declare -f "$FUNC_NAME" 2>/dev/null || true)
if [ -z "$func_body" ]; then
    exit 0
fi

# Reset all overridable variables so we only capture what the function sets
unset pkgdesc install changelog
arch=() groups=() license=() checkdepends=() depends=() optdepends=()
provides=() conflicts=() replaces=() options=() backup=()

# Track which variables are found in the function
declare -A found_vars

# Parse function body line by line, evaluating only variable assignments
while IFS= read -r line; do
    # Trim leading whitespace
    trimmed="${line#"${line%%[![:space:]]*}"}"
    # Match overridable variable assignments
    for varname in pkgdesc depends provides conflicts replaces options backup install optdepends groups changelog arch license checkdepends; do
        if [[ "$trimmed" == "${varname}="* ]]; then
            eval "$trimmed"
            found_vars["$varname"]=1
            break
        fi
    done
done <<< "$func_body"

# Output only variables that were found in the function
for key in pkgdesc install changelog; do
    if [ "${found_vars[$key]:-}" = "1" ]; then
        eval "val=\${$key:-}"
        if [ -n "$val" ]; then
            printf 'S\t%s\t%s\n' "$key" "$val"
        fi
    fi
done

for key in arch groups license checkdepends depends optdepends provides conflicts replaces options backup; do
    if [ "${found_vars[$key]:-}" = "1" ]; then
        eval "count=\${#${key}[@]}"
        if [ "$count" -gt 0 ]; then
            eval "arr=(\"\${${key}[@]}\")"
            for val in "${arr[@]}"; do
                if [ -n "$val" ]; then
                    printf 'A\t%s\t%s\n' "$key" "$val"
                fi
            done
        fi
    fi
done
