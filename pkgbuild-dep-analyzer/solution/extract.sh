#!/bin/bash
#
# Extract PKGBUILD metadata by sourcing each file in bash, then emitting
# structured JSON via jq.  Handles split packages by calling package_<name>()
# with dangerous commands (cd, make, install, etc.) overridden to no-ops.

PKGBUILD_DIR="/app/pkgbuilds"
OUTPUT="/app/output/extracted.json"

mkdir -p /app/output

arr_to_json() {
    if [ $# -eq 0 ]; then
        echo '[]'
        return
    fi
    printf '%s\n' "$@" | jq -R . | jq -s .
}

all_results=()

for pkgfile in "$PKGBUILD_DIR"/PKGBUILD_*; do
    result=$(
        # Source the PKGBUILD in this subshell
        source "$pkgfile" 2>/dev/null

        _pkgbase="${pkgbase:-${pkgname[0]}}"

        # Capture global values before any function calls
        _g_depends=("${depends[@]}")
        _g_provides=("${provides[@]}")
        _g_conflicts=("${conflicts[@]}")
        _g_pkgdesc="$pkgdesc"

        # Build global section JSON
        global_json=$(jq -n \
            --arg pkgbase "$_pkgbase" \
            --arg pkgver "$pkgver" \
            --arg pkgrel "$pkgrel" \
            --arg epoch "${epoch:-}" \
            --arg pkgdesc "$pkgdesc" \
            --arg url "$url" \
            --argjson pkgname "$(arr_to_json "${pkgname[@]}")" \
            --argjson arch "$(arr_to_json "${arch[@]}")" \
            --argjson license "$(arr_to_json "${license[@]}")" \
            --argjson makedepends "$(arr_to_json "${makedepends[@]}")" \
            --argjson depends "$(arr_to_json "${_g_depends[@]}")" \
            --argjson provides "$(arr_to_json "${_g_provides[@]}")" \
            --argjson conflicts "$(arr_to_json "${_g_conflicts[@]}")" \
            --argjson source_arr "$(arr_to_json "${source[@]}")" \
            --argjson sha256sums "$(arr_to_json "${sha256sums[@]}")" \
            '{
                pkgbase: $pkgbase,
                pkgver: $pkgver,
                pkgrel: $pkgrel,
                epoch: $epoch,
                pkgdesc: $pkgdesc,
                url: $url,
                pkgname: $pkgname,
                arch: $arch,
                license: $license,
                makedepends: $makedepends,
                depends: $depends,
                provides: $provides,
                conflicts: $conflicts,
                source: $source_arr,
                sha256sums: $sha256sums
            }')

        # Override commands so package_*() functions are safe to call
        cd()      { :; }
        make()    { :; }
        install() { :; }
        cmake()   { :; }
        meson()   { :; }
        go()      { :; }
        npm()     { :; }
        cargo()   { :; }
        python()  { :; }

        pkg_overrides="[]"

        for pname in "${pkgname[@]}"; do
            func="package_${pname}"
            if declare -f "$func" >/dev/null 2>&1; then
                # Reset to global values before calling function
                depends=("${_g_depends[@]}")
                provides=("${_g_provides[@]}")
                conflicts=("${_g_conflicts[@]}")
                pkgdesc="$_g_pkgdesc"

                # Call the function — only variable assignments take effect
                "$func" 2>/dev/null

                override=$(jq -n \
                    --arg name "$pname" \
                    --arg pkgdesc "$pkgdesc" \
                    --argjson depends "$(arr_to_json "${depends[@]}")" \
                    --argjson provides "$(arr_to_json "${provides[@]}")" \
                    --argjson conflicts "$(arr_to_json "${conflicts[@]}")" \
                    '{
                        name: $name,
                        pkgdesc: $pkgdesc,
                        depends: $depends,
                        provides: $provides,
                        conflicts: $conflicts,
                        has_override: true
                    }')
            else
                override=$(jq -n --arg name "$pname" '{name: $name, has_override: false}')
            fi

            pkg_overrides=$(echo "$pkg_overrides" | jq --argjson o "$override" '. + [$o]')
        done

        echo "$global_json" | jq --argjson pkgs "$pkg_overrides" '. + {packages: $pkgs}'
    )
    all_results+=("$result")
done

printf '%s\n' "${all_results[@]}" | jq -s . > "$OUTPUT"
