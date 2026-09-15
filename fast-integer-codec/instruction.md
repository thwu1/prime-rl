A C shared library for fast integer serialization is at `/app/`. Build it with `make` in `/app/`. The header `fastnum.h` specifies the exact behavioral contract for five functions: `uint64_to_dec`, `dec_to_uint64`, `bytes_to_hex`, `hex_to_bytes`, and `uint64_mul_overflow`.

The source implementation does not fully conform to this specification. Evaluate the correctness of every function against its documented contract — test each across its full input domain, including boundary values and edge cases. Diagnose the root cause of each conformance failure, fix it, and rebuild `/app/libfastnum.so`.

A stripped reference binary compiled from a known-correct implementation is at `/opt/reference/libfastnum_ref.so`. Two standalone hex encoding implementations using different strategies are provided at `/opt/variants/hex_table.c` and `/opt/variants/hex_arithmetic.c`.

Produce these output files:

**`/app/libfastnum.so`** — the corrected, fully conformant shared library.

**`/app/bug_manifest.json`** — a JSON array documenting every conformance issue found, one object per issue, each with:
- `function` — name of the affected library function
- `category` — exactly one of: `"off-by-one"`, `"missing-case"`, `"wrong-constant"`, `"unimplemented"`, `"data-error"`
- `impact` — one sentence describing what inputs trigger incorrect behavior

**`/app/analysis.json`** — a JSON object with:
- `ref_exported_functions` — sorted list of FUNC-type names from the reference binary's dynamic symbol table
- `ref_hex_approach` — `"table"` or `"arithmetic"`: which hex encoding strategy the reference binary employs
- `table_variant_has_rodata_table` — boolean: whether the table variant compiled at `-O2` stores a hex character lookup in its read-only data section
- `arithmetic_variant_has_rodata_table` — boolean: same check for the arithmetic variant
- `higher_throughput_variant` — `"table"` or `"arithmetic"`: which variant is better suited for high-throughput encoding of large byte arrays, based on your evaluation of the compiled output and its optimization characteristics

**`/app/answers.txt`** — two integers, one per line, no labels:
- Line 1: the maximum `uint64_t` value M such that M × 10 does **not** overflow `uint64_t`
- Line 2: the total count of distinct valid 20-digit decimal strings that represent a `uint64_t` value