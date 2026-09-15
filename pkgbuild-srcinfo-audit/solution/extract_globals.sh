#!/bin/bash
# Extract global variables from a PKGBUILD using bash's own parser.
# Usage: extract_globals.sh <pkgbuild_directory>
# Output: tab-separated lines of type\tkey\tvalue
#   S\tkey\tvalue  — scalar
#   A\tkey\tvalue  — one array element

set -e
PKGDIR="$1"
cd "$PKGDIR"
source PKGBUILD

# Default pkgbase to pkgname if not set
if [ -z "$pkgbase" ]; then
    pkgbase="${pkgname}"
fi

# Output scalar fields
for key in pkgbase pkgver pkgrel epoch pkgdesc url install changelog; do
    eval "val=\${$key:-}"
    if [ -n "$val" ]; then
        printf 'S\t%s\t%s\n' "$key" "$val"
    fi
done

# Output array fields
for key in pkgname arch groups license checkdepends makedepends depends optdepends provides conflicts replaces options backup validpgpkeys noextract source md5sums sha1sums sha224sums sha256sums sha384sums sha512sums b2sums; do
    eval "count=\${#${key}[@]}"
    if [ "$count" -gt 0 ]; then
        eval "arr=(\"\${${key}[@]}\")"
        for val in "${arr[@]}"; do
            if [ -n "$val" ]; then
                printf 'A\t%s\t%s\n' "$key" "$val"
            fi
        done
    fi
done
