#!/bin/bash

set -euo pipefail

# 1. Deploy the custom mutator
cp /solution/mutator_solution.py /app/mutator.py

# 2. Build instrumented targets
mkdir -p /app/build
cd /app/target

# Standard AFL++ instrumented binary
afl-clang-fast -o /app/build/target_afl target.c -lz -O2

# CmpLog binary (extra comparison logging instrumentation)
AFL_LLVM_CMPLOG=1 afl-clang-fast -o /app/build/target_cmplog target.c -lz -O2

# 3. Generate seed corpus
python3 /solution/gen_corpus.py

echo "Fuzzing pipeline ready."
echo "  Mutator:  /app/mutator.py"
echo "  Target:   /app/build/target_afl"
echo "  CmpLog:   /app/build/target_cmplog"
echo "  Corpus:   /app/corpus/"
