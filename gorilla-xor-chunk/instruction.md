The directory `/app/` contains a Go module (`gorillachunk`) implementing a time-series float sample chunk encoder/decoder. The module consists of:

- `/app/bstream.go` — bit-level stream reader/writer (do not modify)
- `/app/chunk.go` — type definitions for `Iterator`, `Appender`, `ValueType` (do not modify)
- `/app/xor.go` — `XORChunk` encoder/decoder with **bugs** causing incorrect round-trip behavior for certain float value patterns and timestamp sequences
- `/app/varbit.go` — variable-width integer encoding/decoding functions (stubs, unimplemented)
- `/app/merge.go` — chunk merge function (stub, unimplemented)

**Requirements:**

1. Fix all bugs in `/app/xor.go` so that encoding followed by decoding produces bit-identical timestamp/value pairs for all valid `float64` values (including special values, subnormals, infinities, NaN, negative zero) and all `int64` timestamps. The existing tests exercise edge cases across the full range of 64-bit float patterns and timestamp delta-of-delta boundary values.

2. Implement the four functions in `/app/varbit.go`: `putVarbitInt`, `readVarbitInt`, `putVarbitUint`, `readVarbitUint`. The function signatures, documentation, and encoding specification are provided in the source file. Values must round-trip correctly for the full range of `int64` and `uint64` inputs, including exact bucket boundary values and sequential multi-value streams.

3. Implement `MergeChunks` in `/app/merge.go`. The function signature and behavioral contract are documented in the source file. Both empty and non-empty chunks must be handled correctly.

**Verification:**

```
cd /app && go test -v -count=1 -timeout=120s ./...
```

All tests must pass.
