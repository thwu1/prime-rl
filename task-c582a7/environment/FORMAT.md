# Codec Input Formats

## Decode mode (`python3 /app/codec.py decode <file.json>`)

```json
{
  "table": {
    "timestamp": null | {"format": "<timestamp format string>"},
    "entries": {
      "<index>": {"tag": "<Tag>", "format": "<format string>"},
      ...
    }
  },
  "frames": ["<hex-encoded frame bytes>", ...]
}
```

Output: one human-readable log line per frame.
Format: `[timestamp] LEVEL message`

## Encode mode (`python3 /app/codec.py encode <file.json>`)

```json
{
  "table": {
    "timestamp": null | {"format": "<timestamp format string>"},
    "entries": {
      "<index>": {"tag": "<Tag>", "format": "<format string>"},
      ...
    }
  },
  "logs": [
    {
      "index": <integer entry index>,
      "values": [<value>, ...],
      "timestamp_values": [<value>, ...]
    },
    ...
  ]
}
```

Output: one hex-encoded binary frame per log entry.

### Value representation

Values in `values` and `timestamp_values` arrays correspond to arguments
in the format string, ordered by first-appearance argument index.
Arguments with reused indices (e.g. `{0=u8} {0=u8}`) appear only once.

- **Integers** (u8-u128, i8-i128): JSON number
- **bool**: JSON boolean (`true`/`false`)
- **char**: JSON string of length 1
- **f32, f64**: JSON number
- **str**: JSON string
- **byte slice** (`[u8]`, `[u8;N]`): JSON string of hex bytes (e.g. `"172a"`)
- **Nested Format** (`{=?}`): `{"format_ref": <index>, "values": [...]}`
- **FormatSlice** (`{=[?]}`, `{=[?;N]}`): `[{"format_ref": <index>, "values": [...]}, ...]`
- **FormatSequence** (`{=__internal_FormatSequence}`): `[{"format_ref": <index>, "values": [...]}, ...]`
- **Bitfield** (`{=M..N}`): JSON string of hex bytes for the raw bitfield data

### Wire format summary

Each frame starts with a u16 LE entry index. If a timestamp format is
defined, timestamp arguments follow immediately. Then message arguments
follow in index order.

Argument encoding by type:
- u8: 1 byte
- u16: 2 bytes LE
- u32: 4 bytes LE
- u64: 8 bytes LE
- u128: 16 bytes LE
- i8: 1 byte (two's complement)
- i16: 2 bytes LE (two's complement)
- i32: 4 bytes LE (two's complement)
- i64: 8 bytes LE (two's complement)
- i128: 16 bytes LE (two's complement)
- bool: 1 byte (0x00 = false, 0x01 = true)
- char: 4 bytes LE (Unicode code point)
- f32: 4 bytes LE (IEEE 754)
- f64: 8 bytes LE (IEEE 754)
- str: u32 LE length prefix + UTF-8 bytes
- [u8]: u32 LE length prefix + raw bytes
- [u8;N]: N raw bytes (no length prefix)
- Format ({=?}): u16 LE sub-entry index + serialized sub-arguments
- [?] (FormatSlice): u32 LE count + repeated (u16 LE index + sub-arguments)
- [?;N] (FormatArray): N repetitions of (u16 LE index + sub-arguments)
- FormatSequence: repeated (u16 LE index + sub-arguments) + u16 LE 0x0000 terminator
- Bitfield: raw bytes covering the bit range (ceil((max_bit)/8) - floor(min_bit/8)) bytes
