#!/bin/bash

set -e

SY_FILE="$1"
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# Step 1: Compile SysY to LLVM IR
/app/sysy_compiler "$SY_FILE" > "$TMPDIR/prog.ll"

# Step 2: Assemble text IR to bitcode
llvm-as "$TMPDIR/prog.ll" -o "$TMPDIR/prog.bc"

# Step 3: Link with runtime bitcode
llvm-link "$TMPDIR/prog.bc" /app/runtime/sylib.bc -o "$TMPDIR/linked.bc"

# Step 4: Execute with lli
set +e
lli "$TMPDIR/linked.bc"
exit $?
