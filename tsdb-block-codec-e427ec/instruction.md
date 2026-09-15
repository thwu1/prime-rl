A Go module at `/app/` contains a `tscodec` package that implements a layered compression pipeline for time-series data. The package has multiple bugs and missing implementations spread across six source files. Fix all issues so that `cd /app && go test ./tscodec/ -count=1` passes.

The package's test file (`/app/tscodec/codec_test.go`) is the authoritative specification. It contains 25+ test functions with byte-exact expected outputs, round-trip assertions, encoding strategy expectations, deduplication semantics, and full pipeline integration checks. The tests are correct and must not be modified.

The six source files that may contain bugs are:
- `/app/tscodec/varint.go` — signed/unsigned varint encoding
- `/app/tscodec/nearest_delta.go` — first-order delta encoding with precision-bit compression
- `/app/tscodec/nearest_delta2.go` — second-order delta encoding
- `/app/tscodec/encoding.go` — encoding strategy selection and unmarshal dispatch
- `/app/tscodec/dedup.go` — timestamp-interval deduplication with conflict resolution
- `/app/tscodec/block.go` — block header binary serialization

Do not modify `/app/tscodec/types.go` or `/app/tscodec/codec_test.go`.

Bugs range from incorrect bit-manipulation expressions and stub functions returning hardcoded values, to missing code paths in switch statements and off-by-one errors in binary deserialization. Failures cascade across layers: a broken low-level codec will cause higher-level encoding and pipeline tests to fail.

**Success:** `cd /app && go test ./tscodec/ -count=1` passes all tests with exit code 0.
