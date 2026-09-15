#!/usr/bin/env python3
"""
Apply compiler optimization fixes to kernels.cpp by reading the original
source and performing source-level transformations for each identified
optimization barrier.

"""

import json
import os

# -----------------------------------------------------------------------
# Read original source
# -----------------------------------------------------------------------
with open("/app/kernels.cpp") as f:
    original = f.read()

code = original

# -----------------------------------------------------------------------
# Fix 1: scale_array — pointer aliasing
#   Problem: coeff is float*, out is float*. The compiler cannot prove
#   that writing out[i] does not modify *coeff, so it must reload *coeff
#   on every iteration (LICM failure due to potential alias).
#   Fix: Hoist *coeff into a local variable before the loop.
# -----------------------------------------------------------------------
code = code.replace(
    """void scale_array(float* out, const float* in, float* coeff, size_t n) {
    for (size_t i = 0; i < n; i++) {
        out[i] = in[i] * (*coeff);
    }
}""",
    """void scale_array(float* out, const float* in, float* coeff, size_t n) {
    float c = *coeff;  // hoist: breaks potential alias with out
    for (size_t i = 0; i < n; i++) {
        out[i] = in[i] * c;
    }
}""",
)

# -----------------------------------------------------------------------
# Fix 2: column_sums — non-unit stride access
#   Problem: The outer loop iterates over columns (j) and the inner loop
#   iterates over rows (i). Access matrix[i * cols + j] with varying i
#   produces a stride of 'cols' elements — poor spatial locality.
#   Fix: Interchange loops so the inner loop iterates over j (contiguous).
# -----------------------------------------------------------------------
code = code.replace(
    """void column_sums(const double* matrix, double* sums, int rows, int cols) {
    for (int j = 0; j < cols; j++) {
        sums[j] = 0.0;
        for (int i = 0; i < rows; i++) {
            sums[j] += matrix[i * cols + j];
        }
    }
}""",
    """void column_sums(const double* matrix, double* sums, int rows, int cols) {
    for (int j = 0; j < cols; j++) {
        sums[j] = 0.0;
    }
    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < cols; j++) {
            sums[j] += matrix[i * cols + j];
        }
    }
}""",
)

# -----------------------------------------------------------------------
# Fix 3: dot_product — loop-carried dependency chain
#   Problem: A single accumulator 'sum' creates a strict sequential
#   dependency: each FP add depends on the previous iteration's result.
#   Without -ffast-math the compiler cannot reorder FP additions, so it
#   cannot auto-vectorize or exploit ILP.
#   Fix: Use 4 independent accumulators to expose instruction-level
#   parallelism, then combine them at the end.
# -----------------------------------------------------------------------
code = code.replace(
    """double dot_product(const double* a, const double* b, size_t n) {
    double sum = 0.0;
    for (size_t i = 0; i < n; i++) {
        sum += a[i] * b[i];
    }
    return sum;
}""",
    """double dot_product(const double* a, const double* b, size_t n) {
    double s0 = 0.0, s1 = 0.0, s2 = 0.0, s3 = 0.0;
    size_t i = 0;
    for (; i + 3 < n; i += 4) {
        s0 += a[i]     * b[i];
        s1 += a[i + 1] * b[i + 1];
        s2 += a[i + 2] * b[i + 2];
        s3 += a[i + 3] * b[i + 3];
    }
    for (; i < n; i++) {
        s0 += a[i] * b[i];
    }
    return (s0 + s2) + (s1 + s3);
}""",
)

# -----------------------------------------------------------------------
# Fix 4: apply_transform — cross-TU function call barrier
#   Problem: my_transform() is defined in transform.cpp (separate
#   translation unit). The compiler cannot see its body, so it cannot
#   inline the call. An opaque function call in the loop body prevents
#   auto-vectorization entirely.
#   Fix: Inline the function body (x*x + 2*x + 1) directly in the loop.
# -----------------------------------------------------------------------
code = code.replace(
    """extern double my_transform(double x);

void apply_transform(double* out, const double* in, size_t n) {
    for (size_t i = 0; i < n; i++) {
        out[i] = my_transform(in[i]);
    }
}""",
    """void apply_transform(double* out, const double* in, size_t n) {
    for (size_t i = 0; i < n; i++) {
        double x = in[i];
        out[i] = x * x + 2.0 * x + 1.0;
    }
}""",
)

# -----------------------------------------------------------------------
# Write optimized source
# -----------------------------------------------------------------------
with open("/app/kernels.cpp", "w") as f:
    f.write(code)

print(f"Applied optimizations to kernels.cpp")
print(f"  Original size: {len(original)} bytes")
print(f"  Optimized size: {len(code)} bytes")

# -----------------------------------------------------------------------
# Write analysis.json
# -----------------------------------------------------------------------
analysis = {
    "scale_array": {
        "bottleneck": "pointer_aliasing",
        "explanation": (
            "The parameter 'coeff' (float*) can alias with 'out' (float*). "
            "Writing out[i] could modify *coeff, so the compiler must reload "
            "*coeff on every iteration — a loop-invariant code motion (LICM) "
            "failure. Fix: hoist *coeff to a local variable before the loop, "
            "proving to the compiler that its value is invariant."
        ),
    },
    "column_sums": {
        "bottleneck": "non_unit_stride",
        "explanation": (
            "The inner loop iterates over rows (i) while accessing "
            "matrix[i * cols + j] — a stride of 'cols' elements per iteration. "
            "This non-contiguous access pattern causes frequent cache line "
            "evictions. Fix: interchange the loop nest so the inner loop "
            "iterates over columns (j), producing unit-stride sequential "
            "access through the row-major matrix."
        ),
    },
    "dot_product": {
        "bottleneck": "dependency_chain",
        "explanation": (
            "The single accumulator 'sum' creates a loop-carried dependency "
            "chain: each floating-point addition must complete before the "
            "next can begin. Without -ffast-math, the compiler cannot reorder "
            "FP operations to break this chain. Fix: use 4 independent "
            "accumulators (s0-s3) to expose instruction-level parallelism, "
            "then combine them after the loop."
        ),
    },
    "apply_transform": {
        "bottleneck": "function_call",
        "explanation": (
            "my_transform() is defined in transform.cpp (a separate "
            "translation unit). Without link-time optimization, the compiler "
            "cannot see the function body and therefore cannot inline the "
            "call. An opaque function call in the loop body is an absolute "
            "barrier to auto-vectorization. Fix: inline the function body "
            "(x*x + 2*x + 1) directly in the loop."
        ),
    },
}

with open("/app/analysis.json", "w") as f:
    json.dump(analysis, f, indent=4)

print("Wrote /app/analysis.json")
