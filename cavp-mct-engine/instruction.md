Implement a NIST CAVP-compliant AES-CBC Monte Carlo Test (MCT) validation engine.

The AES MCT algorithm, defined in the NIST AESAVS specification, uses an outer loop of 100 iterations each containing an inner loop of 1000 single-block AES-CBC operations. Between inner iterations, plaintext (or ciphertext in decrypt mode) and IV values rotate according to CBC feedback rules specific to MCT. Between outer iterations, a key derivation step XORs the current key with recent output blocks, where the derivation material width depends on the key length (128, 192, or 256 bits).

## Environment

- `/app/vectors/` -- Reference NIST CAVP `.rsp` format test vectors for AES-CBC MCT (128/192/256-bit, encrypt). Use these to validate your implementation.
- `/app/audit/CBCMCT128_suspect.rsp` -- An AES-128-CBC MCT encrypt file where some `CIPHERTEXT` values have been deliberately altered.
- `/app/challenge.json` -- Defines compute tasks and an audit task.

## Requirements

1. Implement AES-CBC MCT for both **encrypt** and **decrypt** directions, supporting **128, 192, and 256-bit** keys. The key derivation between outer iterations uses different amounts of prior output depending on key size.

2. For each entry in `compute` in `/app/challenge.json`, run the full 100-iteration outer MCT loop and emit the outer-loop state at every requested COUNT index. Each state record contains `KEY`, `IV`, `PLAINTEXT`, and `CIPHERTEXT` (the last being the output of the 1000-iteration inner loop for that outer iteration).

3. For the audit task, determine which entries in the suspect `.rsp` file have a `CIPHERTEXT` that disagrees with what the MCT inner loop produces from the entry's `KEY`, `IV`, and `PLAINTEXT`. Report each corruption.

4. Write all results to `/app/results.json`:

```json
{
  "compute": {
    "<task_id>": {
      "<count>": {
        "KEY": "<hex>",
        "IV": "<hex>",
        "PLAINTEXT": "<hex>",
        "CIPHERTEXT": "<hex>"
      }
    }
  },
  "audit": {
    "<task_id>": [
      {
        "count": <int>,
        "found": "<hex>",
        "expected": "<hex>"
      }
    ]
  }
}
```

All hex strings must be lowercase without `0x` prefix.