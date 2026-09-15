#!/bin/bash

set -euo pipefail

# Restore source files from persistent backup into /app
cp -f /opt/fastnum_src/* /app/

cd /app

# -----------------------------------------------------------------------
# Part 1: Fix all bugs in fastnum.c
# -----------------------------------------------------------------------
python3 /solution/fix_bugs.py

# Rebuild the shared library
make clean || true
make

# -----------------------------------------------------------------------
# Part 2: Binary analysis of reference binary and hex variants
# -----------------------------------------------------------------------
python3 /solution/analyze.py

# -----------------------------------------------------------------------
# Part 3: Compute mathematical answers
# -----------------------------------------------------------------------
python3 -c "
uint64_max = 2**64 - 1

# Answer 1: Maximum uint64 value M such that M * 10 does NOT overflow uint64.
m = uint64_max // 10
print(m)

# Answer 2: Count of valid 20-digit decimal representations of uint64 values.
# Range: 10^19 .. UINT64_MAX inclusive
count = uint64_max - 10**19 + 1
print(count)
" > /app/answers.txt

# -----------------------------------------------------------------------
# Part 4: Generate bug manifest
# -----------------------------------------------------------------------
python3 /solution/write_manifest.py

echo "Solution complete."
