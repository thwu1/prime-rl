#!/bin/bash

set -e

# Step 1: Apply source-level optimization fixes via computational transformation
python3 /solution/apply_optimizations.py

# Step 2: Build the optimized program
cd /app
make clean && make all

# Step 3: Generate llvm-mca analysis
# Compile original (unfixed) scale_array to assembly for comparison
cat > /tmp/scale_original.cpp << 'SRCEOF'
#include <cstddef>
void scale_array_original(float* out, const float* in, float* coeff, size_t n) {
    for (size_t i = 0; i < n; i++) {
        out[i] = in[i] * (*coeff);
    }
}
SRCEOF

cat > /tmp/scale_optimized.cpp << 'SRCEOF'
#include <cstddef>
void scale_array_optimized(float* out, const float* in, float* coeff, size_t n) {
    float c = *coeff;
    for (size_t i = 0; i < n; i++) {
        out[i] = in[i] * c;
    }
}
SRCEOF

# Determine the llvm-mca binary name (may be versioned)
LLVM_MCA=$(which llvm-mca 2>/dev/null || which llvm-mca-18 2>/dev/null || which llvm-mca-17 2>/dev/null || echo "llvm-mca")

# Generate assembly with clang
clang++ -O3 -S -o /tmp/scale_original.s /tmp/scale_original.cpp
clang++ -O3 -S -o /tmp/scale_optimized.s /tmp/scale_optimized.cpp

# Run llvm-mca on both versions and capture output
{
    echo "=========================================================="
    echo "llvm-mca analysis: scale_array BEFORE optimization"
    echo "(pointer aliasing forces *coeff reload every iteration)"
    echo "=========================================================="
    echo ""
    $LLVM_MCA /tmp/scale_original.s 2>&1 || true
    echo ""
    echo "=========================================================="
    echo "llvm-mca analysis: scale_array AFTER optimization"
    echo "(aliasing resolved via local variable hoisting)"
    echo "=========================================================="
    echo ""
    $LLVM_MCA /tmp/scale_optimized.s 2>&1 || true
} > /app/llvm_mca_analysis.txt

# Step 4: Verify correctness
./benchmark
echo "All tests passed."
