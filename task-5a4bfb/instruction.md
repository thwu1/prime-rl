The secp256k1 elliptic curve implementation at `/app/secp256k1.py` uses naive double-and-add scalar multiplication that scans all 256 bits of the scalar. Production cryptography libraries exploit special algebraic properties of the secp256k1 curve to perform this operation with roughly half the doublings.

A Rust project at `/app/k256-harness/` depends on the RustCrypto k256 crate, which contains a production-grade implementation of this optimization. Build the project with `cargo` and run the resulting binary to observe how the crate transforms curve points. The Rust source file at `/app/reference/k256_projective.rs` contains the relevant constant and method used internally by k256.

Using insights from the Rust harness output and source analysis, create `/app/fast_mul.py` exporting:
- `BETA` (int): the field constant from the Rust source
- `LAMBDA` (int): the corresponding scalar-field constant
- `endomorphism(point)`: the efficient curve point map; return None for identity
- `decompose_scalar(k)`: split scalar k into (k1, k2) with k ≡ k1 + k2·LAMBDA (mod n) and |k1|, |k2| < 2^129
- `fast_mul(k, point)`: compute k·P identically to `point_mul(k, point)` but with fewer doublings

Create `/app/results.json` containing:
```json
{
  "lambda_hex": "<LAMBDA as 0x-prefixed hex>",
  "beta_hex": "<BETA as 0x-prefixed hex>",
  "decomposition_examples": [{"k": "<hex>", "k1": <int>, "k2": <int>}, ...],
  "bip340_vectors_pass": true,
  "benchmark": {"naive_mul_avg_ms": <float>, "fast_mul_avg_ms": <float>, "speedup_ratio": <float>}
}
```

The BIP340 implementation at `/app/bip340.py` and test vectors at `/app/test_vectors.json` serve as a correctness oracle — `fast_mul` applied to BIP340 private keys must yield the same public keys as `point_mul`.