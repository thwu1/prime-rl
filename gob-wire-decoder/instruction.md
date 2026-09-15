A broken Go program at `/app/gobdecode/` must be fixed so that it correctly parses raw gob wire-format byte streams **without importing `encoding/gob`** and emits a JSON representation of every value in the stream.

The program reads a binary gob stream from stdin and writes a JSON array to stdout. Each element corresponds to one top-level `Encode` call in the original stream.

**JSON output mappings:**

- Struct → JSON object keyed by field name
- Signed/unsigned integers → JSON numbers
- Floats → JSON numbers (full `float64` precision); NaN/Inf become the strings `"NaN"`, `"+Inf"`, `"-Inf"`
- Booleans → JSON booleans
- Strings → JSON strings
- `[]byte` → base64-encoded JSON string (standard encoding, padded)
- Slices/arrays → JSON arrays
- Maps → JSON objects (keys stringified: ints as decimal, floats as `%g`, bools as `"true"`/`"false"`)
- Complex numbers → `{"Re":<v>,"Im":<v>}` where each component follows the same NaN/Inf string rules as float
- Nil interface → JSON `null`; non-nil interface → the decoded concrete value
- Zero-valued struct fields omitted from the wire stream must appear in the output with their type-appropriate zero (e.g., `0` for int, `""` for string, recursively initialized zero object for nested struct types)

The decoder must handle: all predefined scalar types (bool, int, uint, float64, string, `[]byte`, complex128, interface), user-defined structs with nested types, slices, arrays, maps, interface values carrying predefined concrete types, multi-value streams containing multiple types whose type definitions persist across messages, and empty input (producing `[]`).

**Constraint:** source under `/app/gobdecode/` must not import `encoding/gob`.

**Build:**

```
cd /app/gobdecode && go build -o gobdecode .
```

**Test fixture generation:** `/app/generate_tests.go` uses `encoding/gob` to produce reference `.gob`/`.json` fixture pairs. Build and run it to populate `/app/testdata/`:

```
cd /app && go run generate_tests.go
```

**Success:** `gobdecode` builds without errors, and for every fixture pair in `/app/testdata/`, its JSON output matches the reference JSON after compact normalization (`json.Compact` with sorted keys).
