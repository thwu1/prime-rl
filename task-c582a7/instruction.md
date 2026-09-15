`defmt` is a compact logging framework for embedded microcontrollers. On-target, format strings are replaced by integer indices into an interned string table and arguments are serialized as binary data. A host-side codec must be able to both **encode** (serialize structured log data into binary frames) and **decode** (reconstruct human-readable text from binary frames).

Implement a Python tool at `/app/codec.py` that provides both encoding and decoding of defmt binary frames. The tool must support two subcommands:

```
python3 /app/codec.py encode <input.json>     # structured logs -> hex frames, one per line
python3 /app/codec.py decode <scenario.json>   # hex frames -> human-readable lines, one per line
```

**Encode mode** takes a JSON file describing a string table and a list of log entries with typed argument values, and outputs one hex-encoded binary frame per line. The encoder must parse format strings from the table to determine argument types and serialization order, then produce wire-compatible binary using the correct encoding for each type.

**Decode mode** takes a JSON file containing a string table and hex-encoded binary frames, and outputs one human-readable log line per line. The decoder must parse binary frames, look up format strings, read typed arguments, and apply display hints.

Both modes share a common string table format:
```json
{
  "table": {
    "timestamp": null | {"format": "<format string>"},
    "entries": { "<index>": {"tag": "<Tag>", "format": "<format string>"}, ... }
  }
}
```

Encode-mode input adds a `logs` array; decode-mode input adds a `frames` array. See `/app/FORMAT.md` for the full input schema and value representation rules.

The Rust reference implementation at `/app/ref/` defines the authoritative wire format. No English wire-format specification is provided -- the Rust source IS the spec:

- `/app/ref/lib.rs` -- `Table::decode()`, `Arg` types, argument reading, `Decoder` logic, unit tests showing exact byte layouts
- `/app/ref/frame.rs` -- `Frame` display: format hints (hex/bin/oct/ascii/ISO8601), bitfield extraction, signed-integer formatting via `I128Hex`, hint propagation through nested Format types, timestamp display
- `/app/ref/parser.rs` -- Format string parser: parameter syntax `{[index][=type][:hint]}`, type specifiers, display hint parsing, bitfield range syntax

Your codec must correctly handle: all integer types (u8-u128, i8-i128), bool, char, f32, f64, strings, byte slices (`[u8]`), fixed-length byte arrays (`[u8;N]`), nested Format (`{=?}`), FormatSlice (`{=[?]}`), FormatSequence (`{=__internal_FormatSequence}`), fixed-length format arrays (`{=[?;N]}`), bitfield ranges (`{=M..N}`), all display hints (hex, binary, octal, ascii, Debug propagation, ISO 8601, us/ms time), timestamps, and argument index reuse (`{0=u8} {0=u8}`).