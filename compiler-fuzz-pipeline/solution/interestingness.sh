#!/bin/bash

# Interestingness test for test case reduction.
# Usage: interestingness.sh <c-file>
# Exits 0 (interesting) iff the file exhibits a genuine optimization-level
# behavioral divergence with no undefined behavior.

FILE="${1}"
if [ -z "$FILE" ]; then
    exit 1
fi

# Resolve to absolute path if relative
case "$FILE" in
    /*) ;;
    *)  FILE="$(pwd)/$FILE" ;;
esac

WORK=$(mktemp -d)
trap "rm -rf $WORK" EXIT

TIMEOUT=5

# Compile with gcc -O0
gcc -O0 -w -o "$WORK/bin_O0" "$FILE" -lm 2>/dev/null || exit 1

# Compile with gcc -O2
gcc -O2 -w -o "$WORK/bin_O2" "$FILE" -lm 2>/dev/null || exit 1

# Run O0 binary
OUT_O0=$(timeout $TIMEOUT "$WORK/bin_O0" 2>/dev/null)
RC_O0=$?
# Reject on timeout (124) or signal death (>=128)
[ $RC_O0 -ge 124 ] && exit 1

# Run O2 binary
OUT_O2=$(timeout $TIMEOUT "$WORK/bin_O2" 2>/dev/null)
RC_O2=$?
[ $RC_O2 -ge 124 ] && exit 1

# Outputs must differ
[ "$OUT_O0" = "$OUT_O2" ] && exit 1

# UBSan check — reject if undefined behavior detected
gcc -fsanitize=undefined -O0 -w -o "$WORK/bin_ubsan" "$FILE" -lm 2>/dev/null || exit 1

timeout $TIMEOUT "$WORK/bin_ubsan" >/dev/null 2>"$WORK/ubsan_err.txt"
UBSAN_RC=$?

# Reject if UBSan binary crashed/timed-out
[ $UBSAN_RC -ge 124 ] && exit 1

# Reject if UBSan reported any runtime error
grep -q "runtime error" "$WORK/ubsan_err.txt" 2>/dev/null && exit 1

# All checks passed: file is interesting
exit 0
