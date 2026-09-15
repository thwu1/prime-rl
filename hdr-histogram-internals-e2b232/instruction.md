The file `/app/src/HdrHistogram.java` contains an incomplete implementation of a High Dynamic Range Histogram. Every method throwing `UnsupportedOperationException` must be fully implemented. The already-implemented `getTotalCount()` method and constructors must not be modified.

The file `/app/src/HistogramCodec.java` contains an incomplete codec for encoding and decoding `HdrHistogram` instances into a compact string representation. All TODO methods must be implemented according to the wire format specification documented in the source file's Javadoc.

The project's build system at `/app/Makefile` must produce compiled class files at `/app/classes/` when `make build` is invoked from `/app/`. Running `make all` must build and then execute the codec's round-trip verification, printing `ROUNDTRIP_OK` on success. The provided Makefile contains defects that must be corrected.

**HdrHistogram behavioral requirements:**

- Constructor validation: `lowestDiscernibleValue >= 1`, `highestTrackableValue >= 2 * lowestDiscernibleValue`, `numberOfSignificantValueDigits` in `[0, 5]`. The precision/unit-magnitude combination must not exceed 62 bits of addressable range. Violations throw `IllegalArgumentException`.
- `recordValue`/`recordValueWithCount`: throw `ArrayIndexOutOfBoundsException` for values outside the trackable range. Must maintain min/max tracking state.
- `recordValueWithExpectedInterval`: backfill intermediate values to compensate for coordinated omission when the value exceeds the expected interval.
- `subtract`: throws `IllegalArgumentException` on negative resulting counts or out-of-range values. Min/max must be recomputed after subtraction.
- `add`: must handle both structurally identical and structurally different histograms.
- `getValueAtPercentile(0.0)` returns the lowest equivalent value; all other percentiles return the highest equivalent value of the matching bucket.
- `getMean`, `getStdDeviation` return `0.0` for empty histograms. `getPercentileAtOrBelowValue` returns `100.0` for empty histograms.
- `getMinNonZeroValue` returns `Long.MAX_VALUE` when no non-zero values have been recorded.
- Index math must satisfy the round-trip invariant: `countsArrayIndex(valueFromIndex(i)) == i`.

**Codec requirements:**

- Encoding must be deterministic for any given histogram state.
- Decoding the encoded string must reconstruct a histogram with identical per-index counts, `totalCount`, min/max, mean, and percentile query results.

**Build:** `make -C /app build`

**Tests:** `bash /tests/test.sh`

All tests must pass for the task to be considered complete.
