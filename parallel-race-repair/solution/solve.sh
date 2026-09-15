#!/bin/bash

# Copy correct parallel implementations into place
cp /solution/fixed/histogram.cpp  /app/src/histogram.cpp
cp /solution/fixed/jacobi.cpp     /app/src/jacobi.cpp
cp /solution/fixed/knn_search.cpp /app/src/knn_search.cpp
cp /solution/fixed/lu_factor.cpp  /app/src/lu_factor.cpp

# Generate verdicts.json via analysis script
python3 /solution/write_verdicts.py

cd /app
export OMP_NUM_THREADS=4

# Build both normal and TSan variants
make clean && make all && make tsan

# Verify correctness for all programs
for prog in histogram jacobi knn_search lu_factor; do
    echo "=== Correctness: $prog ==="
    ./$prog
    if [ $? -ne 0 ]; then
        echo "FAIL: $prog correctness"
        exit 1
    fi
done

# Verify race-freedom under ThreadSanitizer
for prog in histogram jacobi knn_search lu_factor; do
    echo "=== TSan: ${prog}_tsan ==="
    TSAN_OPTIONS="exitcode=66 halt_on_error=1 suppressions=/app/tsan.supp" ./${prog}_tsan
    rc=$?
    if [ $rc -eq 66 ]; then
        echo "FAIL: $prog has data races"
        exit 1
    fi
done

echo "All programs implemented and verified successfully."
