#!/usr/bin/env python3
"""
Generate results.json by running correctness checks and benchmarks.

"""

import sys
import json
import time

sys.path.insert(0, '/app')

from secp256k1 import G, N, point_mul
from fast_mul import fast_mul, LAMBDA, BETA, decompose_scalar, endomorphism

# ============================================================================
# Verify constants
# ============================================================================

print("=== Verifying constants ===")

from secp256k1 import P
assert pow(BETA, 3, P) == 1, "BETA is not a cube root of unity in F_p"
assert BETA != 1, "BETA is trivial"
print(f"  BETA: {hex(BETA)}")
print(f"  BETA^3 mod p = 1")

assert pow(LAMBDA, 3, N) == 1, "LAMBDA is not a cube root of unity in Z_n"
assert LAMBDA != 1, "LAMBDA is trivial"
print(f"  LAMBDA: {hex(LAMBDA)}")
print(f"  LAMBDA^3 mod n = 1")

endo_G = endomorphism(G)
lambda_G = point_mul(LAMBDA, G)
assert endo_G == lambda_G, "Eigenvalue property failed"
print(f"  endo(G) = LAMBDA*G")

# ============================================================================
# Test optimized multiplication against naive point_mul
# ============================================================================

print("\n=== Testing fast_mul ===")

test_scalars = [
    1, 2, 3, 7, 255,
    0x03,
    0xB7E151628AED2A6ABF7158809CF4F3C762E7160F38B4DA56A784D9045190CFEF,
    0xC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B14E5C9,
    0x0B432B2677937381AEF05BB02A66ECD012773062CF3FA2549E44F58ED2401710,
    N - 1,
    LAMBDA,
]

for k in test_scalars:
    expected = point_mul(k, G)
    actual = fast_mul(k, G)
    assert actual == expected, f"Mismatch for k={hex(k)}"
    print(f"  k={hex(k)[:20]}... ok")

assert fast_mul(0, G) is None, "fast_mul(0, G) should be None"
assert fast_mul(N, G) is None, "fast_mul(N, G) should be None"
print("  Edge cases ok")

# ============================================================================
# Verify BIP340 test vectors
# ============================================================================

print("\n=== Verifying BIP340 test vectors ===")

import bip340

with open('/app/test_vectors.json', 'r') as f:
    vectors = json.load(f)

bip340_pass = True

for v in vectors['signing_vectors']:
    sig = bip340.schnorr_sign(
        bytes.fromhex(v['message']),
        bytes.fromhex(v['secret_key']),
        bytes.fromhex(v['aux_rand'])
    )
    if sig is None or sig.hex().lower() != v['signature'].lower():
        print(f"  Signing vector {v['index']}: FAIL")
        bip340_pass = False
    else:
        print(f"  Signing vector {v['index']}: PASS")

for v in vectors['verification_vectors']:
    result = bip340.schnorr_verify(
        bytes.fromhex(v['message']),
        bytes.fromhex(v['public_key']),
        bytes.fromhex(v['signature'])
    )
    if result != v['valid']:
        print(f"  Verify vector {v['index']}: FAIL")
        bip340_pass = False
    else:
        print(f"  Verify vector {v['index']}: PASS")

for v in vectors['signing_vectors']:
    sk = int(v['secret_key'], 16)
    naive_pk = point_mul(sk, G)
    fast_pk = fast_mul(sk, G)
    assert naive_pk == fast_pk, f"Public key mismatch for vector {v['index']}"

print(f"  BIP340 vectors pass: {bip340_pass}")

# ============================================================================
# Benchmark
# ============================================================================

print("\n=== Benchmarking ===")

bench_scalars = [
    0xB7E151628AED2A6ABF7158809CF4F3C762E7160F38B4DA56A784D9045190CFEF,
    0xC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B14E5C9,
    0x0B432B2677937381AEF05BB02A66ECD012773062CF3FA2549E44F58ED2401710,
]

# Warmup
for k in bench_scalars:
    point_mul(k, G)
    fast_mul(k, G)

iterations = 3
start = time.time()
for _ in range(iterations):
    for k in bench_scalars:
        point_mul(k, G)
naive_total = time.time() - start
naive_avg_ms = (naive_total / (iterations * len(bench_scalars))) * 1000

start = time.time()
for _ in range(iterations):
    for k in bench_scalars:
        fast_mul(k, G)
fast_total = time.time() - start
fast_avg_ms = (fast_total / (iterations * len(bench_scalars))) * 1000

speedup = naive_avg_ms / fast_avg_ms if fast_avg_ms > 0 else 0

print(f"  Naive avg: {naive_avg_ms:.2f} ms")
print(f"  Fast avg:  {fast_avg_ms:.2f} ms")
print(f"  Speedup:   {speedup:.2f}x")

# ============================================================================
# Decomposition examples
# ============================================================================

examples = []
for k in bench_scalars:
    k1, k2 = decompose_scalar(k)
    examples.append({"k": hex(k), "k1": k1, "k2": k2})

# ============================================================================
# Write results.json
# ============================================================================

results = {
    "lambda_hex": hex(LAMBDA),
    "beta_hex": hex(BETA),
    "decomposition_examples": examples,
    "bip340_vectors_pass": bip340_pass,
    "benchmark": {
        "naive_mul_avg_ms": round(naive_avg_ms, 2),
        "fast_mul_avg_ms": round(fast_avg_ms, 2),
        "speedup_ratio": round(speedup, 2)
    }
}

with open('/app/results.json', 'w') as f:
    json.dump(results, f, indent=2)

print(f"\n=== Results written to /app/results.json ===")
