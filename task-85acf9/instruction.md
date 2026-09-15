Design and implement a complete canonical ABI layout engine for WebAssembly Component Model types at `/app/cabi.py`.

A skeleton with API signatures, primitive-type constants, and low-level utility functions is provided. Every function that currently raises `NotImplementedError` must be implemented. Type definitions are at `/app/types.json` with corresponding WIT interface definitions at `/app/interface.wit`. Reference byte serializations from a known-correct implementation are at `/app/reference/` (inspect with `xxd`). Tools `wabt` and `xxd` are installed.

Your engine must correctly handle all Component Model type kinds — records, variants, tuples, enums, options, results, flags, and lists — including arbitrarily nested composition. Key design challenges include:

- **Type despecialization**: reducing sugar types (tuple, enum, option, result) to canonical forms before computing layouts.
- **Variant layout arithmetic**: correctly aligning the payload region past the discriminant, and applying trailing alignment to the overall variant size.
- **Flat-type join rule**: when flattening variant payloads into core wasm valtypes, corresponding positions across cases must be joined according to the spec's join function — which has a non-obvious asymmetry between integer and float types.
- **Record trailing padding**: total record size must be rounded up to the record's alignment.
- **Function-type spilling**: `flatten_functype` must apply MAX_FLAT_PARAMS (16) and MAX_FLAT_RESULTS (1) thresholds, replacing over-limit flat representations with a single i32 pointer.
- **List serialization stride**: element stride in contiguous list buffers must account for alignment padding between elements.

The canonical ABI specification is the authoritative reference:
https://github.com/WebAssembly/component-model/blob/main/design/mvp/CanonicalABI.md

Verify your implementation: `python3 /app/check_conformance.py`