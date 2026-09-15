The Go project at `/app/` implements a field-redacting wrapper for the `go.uber.org/zap` structured logging library's `zapcore.Encoder` interface. The wrapper intercepts log fields matching configurable path-based rules and either masks their values with `[REDACTED]` or drops them entirely.

The configuration in `/app/redact/config.go` is correct and must not be modified. Rules use dot-separated field paths with `*` as a single-segment wildcard (e.g., `"user.password"`, `"*.token"`, `"request.headers.authorization"`).

The encoder implementation in `/app/redact/encoder.go` has defects. Top-level primitive field redaction works correctly, but the following behaviors are broken:

- **Nested objects**: When `AddObject("user", marshaler)` is called, the marshaler's `Add*` calls bypass redaction entirely. Fields like `user.password` are never checked against rules.
- **Arrays of objects**: `AddArray` similarly bypasses redaction for objects within arrays.
- **Clone**: `Clone()` does not return a redacting encoder, so cloned loggers lose all redaction capability.
- **EncodeEntry**: Fields passed to `EncodeEntry(entry, fields)` are forwarded to the inner encoder without redaction.

Fix `/app/redact/encoder.go` so that:

1. Redaction rules apply at every nesting depth through objects and arrays.
2. `Clone()` returns a `*redact.Encoder` with independent, correctly-initialized state.
3. `EncodeEntry` applies redaction to entry-level fields and is idempotent across repeated calls.
4. Masked non-string fields are replaced via `AddString(key, "[REDACTED]")` on the inner encoder.

**Validation**: `cd /app && go test -v -count=1 ./redact/` must report all tests passing.
