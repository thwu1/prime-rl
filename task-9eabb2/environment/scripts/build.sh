#!/bin/bash
# build.sh - Build libmfp in different compilation modes
#
# Usage: build.sh <mode> [src_dir] [out_dir]
# Modes:
#   canary  - MAGMA_ENABLE_CANARIES: bug oracles active, bugs still present
#   fixed   - MAGMA_ENABLE_FIXES: bugs fixed, no canaries
#   default - vanilla build with bugs active and no instrumentation

MODE="${1:-default}"
SRC_DIR="${2:-/app/src}"
OUT_DIR="${3:-/app/output}"

mkdir -p "$OUT_DIR"

CFLAGS="-Wall -g -O0"
SRCS="$SRC_DIR/mfp.c $SRC_DIR/driver.c"

case "$MODE" in
    canary)
        CFLAGS="$CFLAGS -DMAGMA_ENABLE_CANARIES -include $SRC_DIR/canary.h"
        SRCS="$SRCS $SRC_DIR/canary.c"
        ;;
    fixed)
        CFLAGS="$CFLAGS -DMAGMA_ENABLE_FIXES"
        ;;
    default)
        ;;
    *)
        echo "ERROR: Unknown mode '$MODE'. Use: canary, fixed, default"
        exit 1
        ;;
esac

gcc $CFLAGS -I"$SRC_DIR" -o "$OUT_DIR/mfp_parser_$MODE" $SRCS
if [ $? -eq 0 ]; then
    echo "Built $OUT_DIR/mfp_parser_$MODE ($MODE mode)"
else
    echo "ERROR: Build failed for $MODE mode"
    exit 1
fi
