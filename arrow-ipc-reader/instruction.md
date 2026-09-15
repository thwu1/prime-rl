A broken Rust program at `/app/arrow_ipc_reader/` must be fixed to correctly read Apache Arrow IPC stream format files (`.arrows`) and convert them to JSON matching the Arrow integration test format.

**Build and run:**

    cd /app/arrow_ipc_reader && cargo build --release
    /app/arrow_ipc_reader/target/release/arrow_ipc_reader <input.arrows> <output.json>

The skeleton at `/app/arrow_ipc_reader/src/main.rs` compiles but produces incorrect output. It contains multiple bugs and is missing support for most Arrow data types. Identify and fix all issues.

**Supported Arrow types:** Null, Bool, Int8/16/32/64, UInt8/16/32/64, Float32/64, Utf8, Binary, List (32-bit offsets), Struct, and dictionary-encoded variants of any of these.

**JSON output format** (Arrow integration test format):

- Top-level: `{"schema": {...}, "batches": [...]}` with optional `"dictionaries": [...]`.
- Schema fields: `{"name", "nullable", "type", "children"}` with optional `"dictionary"`.
- Type objects: `{"name":"int","bitWidth":32,"isSigned":true}`, `{"name":"floatingpoint","precision":"DOUBLE"}` (or `"SINGLE"`), `{"name":"utf8"}`, `{"name":"bool"}`, `{"name":"list"}`, `{"name":"struct"}`, `{"name":"binary"}`, `{"name":"null"}`.
- RecordBatch columns: `{"name", "count", "VALIDITY":[0|1,...], "DATA":[...]}` with `"OFFSET"` for variable-length types and `"children"` for nested types.
- Int64/UInt64 DATA values encoded as JSON strings. Bool DATA as 0/1. Binary DATA as uppercase hex strings.
- Dictionary columns: DATA contains integer indices; dictionary values appear in the `"dictionaries"` array as `{"id", "data": {"count", "columns": [...]}}`.
- Dictionary schema fields include `"dictionary": {"id", "indexType": {...}, "isOrdered": bool}` and `"type"` reflects the value type (not index type).

**Success criteria:** `cargo build --release` succeeds and the binary correctly converts all test `.arrows` files to matching JSON, covering all listed primitive types including Float32, variable-length types (Utf8 and Binary), nested types (List and Struct), standalone Null columns, dictionary encoding, multiple batches, empty batches, and all-null columns.
