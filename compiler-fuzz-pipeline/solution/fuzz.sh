#!/bin/bash

# Differential testing harness for compiler fuzzing.
# Usage: fuzz.sh --seed N | fuzz.sh --file PATH

set -o pipefail

CSMITH_BIN="/app/csmith-src/build/src/csmith"
CSMITH_INCLUDE="/app/csmith-include"
EXEC_TIMEOUT=5

WORK=$(mktemp -d)
trap "rm -rf $WORK" EXIT

# ── Parse arguments ──────────────────────────────────────────────────────

SEED=""
FILE_PATH=""
CFLAGS=""

if [ "$1" = "--seed" ] && [ -n "$2" ]; then
    SEED="$2"
    "$CSMITH_BIN" --seed "$SEED" > "$WORK/test.c" 2>/dev/null
    if [ $? -ne 0 ]; then
        jq -n --arg s "$SEED" '{status:"compile_error",seed:($s|tonumber),outputs:{},details:"csmith generation failed"}'
        exit 0
    fi
    CFLAGS="-I$CSMITH_INCLUDE"
elif [ "$1" = "--file" ] && [ -n "$2" ]; then
    FILE_PATH="$2"
    cp "$FILE_PATH" "$WORK/test.c"
    CFLAGS=""
else
    echo "Usage: $0 --seed N | --file PATH" >&2
    exit 1
fi

# ── Compile & run each configuration ─────────────────────────────────────

run_config() {
    local COMPILER="$1"
    local FLAG="$2"
    local LABEL="$3"

    $COMPILER $FLAG $CFLAGS -w -o "$WORK/bin_$LABEL" "$WORK/test.c" -lm 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "COMPILE_ERROR"
        return 1
    fi

    local OUT
    OUT=$(timeout "$EXEC_TIMEOUT" "$WORK/bin_$LABEL" 2>/dev/null)
    local RC=$?

    if [ $RC -eq 124 ]; then
        echo "TIMEOUT"
        return 2
    elif [ $RC -ge 128 ]; then
        echo "CRASH(signal $((RC - 128)))"
        return 3
    fi

    printf '%s' "$OUT"
    return 0
}

OUTPUT_gcc_O0=$(run_config gcc "-O0" "gcc_O0"); RC_gcc_O0=$?
OUTPUT_gcc_O2=$(run_config gcc "-O2" "gcc_O2"); RC_gcc_O2=$?
OUTPUT_clang_O0=$(run_config clang "-O0" "clang_O0"); RC_clang_O0=$?
OUTPUT_clang_O2=$(run_config clang "-O2" "clang_O2"); RC_clang_O2=$?

# ── Determine status ─────────────────────────────────────────────────────

STATUS="pass"
DETAILS=""

# Check for compile errors
for rc in $RC_gcc_O0 $RC_gcc_O2 $RC_clang_O0 $RC_clang_O2; do
    if [ "$rc" -eq 1 ]; then STATUS="compile_error"; DETAILS="Compilation failed in at least one configuration"; fi
done

# Check for crashes (higher priority)
for rc in $RC_gcc_O0 $RC_gcc_O2 $RC_clang_O0 $RC_clang_O2; do
    if [ "$rc" -eq 3 ]; then STATUS="crash"; DETAILS="Runtime crash in at least one configuration"; fi
done

# Check for timeouts (highest runtime priority)
for rc in $RC_gcc_O0 $RC_gcc_O2 $RC_clang_O0 $RC_clang_O2; do
    if [ "$rc" -eq 2 ]; then STATUS="timeout"; DETAILS="Execution timed out in at least one configuration"; fi
done

# If all ran successfully, check for UB
if [ "$STATUS" = "pass" ]; then
    gcc -fsanitize=undefined -O0 $CFLAGS -w -o "$WORK/bin_ubsan" "$WORK/test.c" -lm 2>/dev/null
    if [ $? -eq 0 ]; then
        timeout "$EXEC_TIMEOUT" "$WORK/bin_ubsan" >/dev/null 2>"$WORK/ubsan_err.txt"
        UBSAN_RC=$?
        if [ $UBSAN_RC -ne 0 ] && [ $UBSAN_RC -ne 124 ]; then
            STATUS="ub"
            DETAILS="UBSan detected undefined behavior (exit $UBSAN_RC)"
        elif grep -q "runtime error" "$WORK/ubsan_err.txt" 2>/dev/null; then
            STATUS="ub"
            DETAILS="UBSan detected undefined behavior"
        fi
    fi
fi

# If still pass, check for output mismatch
if [ "$STATUS" = "pass" ]; then
    MISMATCH=0
    REF="$OUTPUT_gcc_O0"
    for out in "$OUTPUT_gcc_O2" "$OUTPUT_clang_O0" "$OUTPUT_clang_O2"; do
        if [ "$out" != "$REF" ]; then
            MISMATCH=1
            break
        fi
    done
    if [ $MISMATCH -eq 1 ]; then
        STATUS="mismatch"
        DETAILS="Output differs across compiler configurations"
    fi
fi

# ── Emit JSON ─────────────────────────────────────────────────────────────

if [ -n "$SEED" ]; then
    jq -n \
        --arg status "$STATUS" \
        --argjson seed "$SEED" \
        --arg o1 "$OUTPUT_gcc_O0" \
        --arg o2 "$OUTPUT_gcc_O2" \
        --arg o3 "$OUTPUT_clang_O0" \
        --arg o4 "$OUTPUT_clang_O2" \
        --arg details "$DETAILS" \
        '{status:$status, seed:$seed,
          outputs:{gcc_O0:$o1, gcc_O2:$o2, clang_O0:$o3, clang_O2:$o4},
          details:$details}'
else
    jq -n \
        --arg status "$STATUS" \
        --arg file "$FILE_PATH" \
        --arg o1 "$OUTPUT_gcc_O0" \
        --arg o2 "$OUTPUT_gcc_O2" \
        --arg o3 "$OUTPUT_clang_O0" \
        --arg o4 "$OUTPUT_clang_O2" \
        --arg details "$DETAILS" \
        '{status:$status, file:$file,
          outputs:{gcc_O0:$o1, gcc_O2:$o2, clang_O0:$o3, clang_O2:$o4},
          details:$details}'
fi
