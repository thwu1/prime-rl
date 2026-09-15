`/app/knownbits.py` implements the **KnownBits** abstract domain for compiler dataflow analysis — tracking which bits of an integer are *known-zero*, *known-one*, or *unknown* across all possible executions, as in LLVM's `ValueTracking` infrastructure.

`/app/transfers.py` contains skeleton transfer functions for 11 operations that currently return `top()` (all bits unknown). Implement **sound and precise** transfer functions for all 11:

**Bitwise:** `and`, `or`, `xor`
**Shifts:** `shl`, `lshr`, `ashr`
**Arithmetic:** `add`, `sub`, `mul`
**Unary:** `neg`, `not`

## Constraints

**Soundness** (mandatory): For every valid `KnownBits` input combination, every concrete result on concrete values consistent with those inputs must be contained in the returned `KnownBits`. Unsound functions score zero regardless of precision.

**Precision** (scored): `top()` is always sound but earns zero precision. Transfer functions are measured against the optimal result computed by exhaustive enumeration. Required: at least 60% average precision across all operations at 4-bit width, and at least 85% on bitwise operations.

**Efficiency**: O(width) or O(1) time only — no enumeration of concrete values. Functions calling `concrete_set()` or iterating all possible values are rejected.

**Generality**: Correct for any bit width from 4 to 16.

## Verification

Tests exhaustively verify soundness at 4-bit width and measure precision against optimal. Soundness is spot-checked at 8-bit width on sampled inputs.

## Files

- `/app/knownbits.py` — `KnownBits` class, concrete semantics, verification infrastructure. **Do not modify.**
- `/app/transfers.py` — Skeleton transfer functions. **Modify this file.**