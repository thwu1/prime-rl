#!/bin/bash
# apply_patches.sh - Apply MAGMA-format patches to the source tree
#
# Each patch file contains the token %MAGMA_BUG% which is replaced with the
# bug identifier (derived from the patch filename) before application.
#
# Usage: apply_patches.sh [patches_dir] [src_dir]

PATCHES_DIR="${1:-/app/patches}"
SRC_DIR="${2:-/app/src}"

if [ ! -d "$PATCHES_DIR" ]; then
    echo "ERROR: Patches directory not found: $PATCHES_DIR"
    exit 1
fi

if [ ! -d "$SRC_DIR" ]; then
    echo "ERROR: Source directory not found: $SRC_DIR"
    exit 1
fi

PATCH_COUNT=0
for patch in "$PATCHES_DIR"/*.patch; do
    [ -f "$patch" ] || continue
    name=$(basename "$patch" .patch)
    echo "Applying patch $name..."
    sed "s/%MAGMA_BUG%/$name/g" "$patch" | patch -p1 -d "$SRC_DIR" --batch --quiet
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to apply patch $name"
        exit 1
    fi
    PATCH_COUNT=$((PATCH_COUNT + 1))
done

if [ $PATCH_COUNT -eq 0 ]; then
    echo "WARNING: No patch files found in $PATCHES_DIR"
    exit 1
fi

echo "Successfully applied $PATCH_COUNT patch(es)."
