A stripped shared library `/app/libseat.so` implements a 64-bit cryptographic transform. A Python CLI wrapper at `/app/runner.py` provides access:

```
python3 /app/runner.py <hex_value>
python3 /app/runner.py --verify <hex_in> <hex_expected>
```

Three known plaintext/ciphertext pairs are in `/app/test_vectors.json`. Five target ciphertexts requiring decryption are in `/app/targets.json`.

Three previous decryption attempts in `/app/candidates/` each produce incorrect results. Partial reverse engineering notes are in `/app/RE_NOTES.md`. An obfuscated Python re-implementation at `/app/obfuscated.py` claims the transform is "one-way" and "irreversible."

## Deliverables

Write `/app/results.json`: a JSON array of five 16-character lowercase hex strings — the recovered plaintexts for all targets, in order.

Write `/app/candidates/fixed_a.py`, `fixed_b.py`, `fixed_c.py`: minimal corrections to each broken candidate. Each must export `decrypt(ct)` that correctly inverts the transform. Changes must be minimal (>95% character similarity to the original).

Write `/app/kpa_attack.py` exporting:
- `recover_params(pairs)` — given `[(plaintext_int, ciphertext_int), ...]`, recover two integers that fully characterize the transform. Return `(A, B)`.
- `attack_decrypt(ct, A, B)` — decrypt ciphertext integer `ct` using recovered parameters. Return plaintext integer.

The attack must work with any 2 of the 3 test vectors and correctly decrypt all targets plus held-out vectors not used for recovery.

Write `/app/security_assessment.md` (minimum 500 characters): document the fundamental weakness in the construction, evaluate the obfuscated wrapper's security claims, and propose a structural fix.