A Python implementation of the BPF verifier's tnum (tristate number) abstract domain is at `/app/tnum.py`. Each tnum tracks partial bit-level knowledge about a 64-bit register using two fields: `value` (known-one bits) and `mask` (unknown bits), with invariant `value & mask == 0`. The concretization is `gamma(v, m) = { n : n & ~m == v }`.

The implementation contains three soundness bugs in existing operations and two unimplemented operations (`tnum_mul`, `tnum_range`). No formal verification exists.

Identify and fix all soundness bugs in `/app/tnum.py`. Implement the two missing operations. Write `/app/verify.py` using Z3 to formally verify that every tnum operation is sound on 8-bit integers (for all valid abstract inputs and all concrete values in their concretizations, the concrete result of the operation is in the concretization of the abstract result). Save verification results to `/app/verification_report.json`:

```json
{"operation_name": {"verified": true, "bit_width": 8}, ...}
```

Required entries: `tnum_and`, `tnum_or`, `tnum_xor`, `tnum_add`, `tnum_sub`, `tnum_lshift`, `tnum_rshift`, `tnum_intersect`, `tnum_mul`, `tnum_range`.