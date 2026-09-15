Implement sound and precise transfer functions for the KnownBits abstract domain in `/app/transfer_functions.py` and cross-validate them against LLVM's `opt-18` instcombine pass.

The KnownBits domain (`/app/knownbits.py`) represents fixed-width unsigned integers where each bit is known-0, known-1, or unknown. Six transfer functions need implementation: `transfer_add`, `transfer_sub`, `transfer_mul`, `transfer_shl`, `transfer_lshr`, `transfer_udiv`. Reference implementations for AND, OR, XOR, and NOT are provided in the same file.

**Soundness**: For every concrete input pair consistent with the abstract inputs, the concrete result must be contained in the abstract output. Verified exhaustively at 4-bit width over all 6561 abstract input pairs via `/app/verifier.py`.

**Precision** — minimum fraction of knowable bits determined versus the theoretical optimum, averaged over all non-trivial input pairs at 4-bit width:

| Operation | Threshold |
|-----------|-----------|
| `add`     | 0.85      |
| `sub`     | 0.85      |
| `mul`     | 0.55      |
| `shl`     | 0.75      |
| `lshr`    | 0.75      |
| `udiv`    | 0.35      |

**Constant folding**: When both inputs are fully determined (constants), all output bits must be known. Identity operations (subtracting 0, shifting by 0) must preserve all known bits of the input.

**Operation semantics** (unsigned, mod 2^width): `add`/`sub`/`mul` are modular arithmetic. `shl(a,b)` is left shift — result is 0 when b ≥ width. `lshr(a,b)` is logical right shift with zero-fill — result is 0 when b ≥ width. `udiv(a,b)` is integer division — result is 0 when b = 0. When the result is provably a single value (e.g., anything × 0, shift by ≥ width, division where divisor is 0 or always exceeds dividend), the output must be that constant.

## LLVM Cross-Validation

LLVM IR test cases are provided at `/app/ir_testcases/*.ll` — one per operation, each exercising a KnownBits-dependent optimization. For each test case:

- Run `opt-18 -passes=instcombine -S <input>.ll -o /app/ir_testcases/<name>.opt.ll` to produce optimized output.
- Analyze the optimization LLVM applied (e.g., `add` → `or` for disjoint bits, strength reduction of `mul` to `shl`, dead code elimination when result is provably constant).

Produce `/app/cross_validation.json` — a JSON array where each entry has:
- `"operation"`: one of `"add"`, `"sub"`, `"mul"`, `"shl"`, `"lshr"`, `"udiv"`
- `"ir_file"`: path to the input `.ll` file
- `"llvm_optimization"`: description of what LLVM did
- `"consistent"`: boolean — must be `true` for all entries

All six operations must have at least one entry.

## Verification Report

Produce `/app/verification_results.json` — a JSON object keyed by operation name (`"add"`, `"sub"`, `"mul"`, `"shl"`, `"lshr"`, `"udiv"`), each containing:
- `"sound"`: boolean (must be `true`)
- `"precision"`: float (must meet the threshold above)

Compute these using `verify_soundness_binary` and `measure_precision_binary` from `/app/verifier.py`.