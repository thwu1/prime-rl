The program at `/app/` is a standalone Protocol Buffers wire format codec written in Go. It encodes, decodes, and merges protobuf binary data using a JSON schema format, without depending on any protobuf library. The implementation contains multiple interacting bugs across `wire.go`, `codec.go`, and `merge.go`.

CLI commands:

- `./pbcodec decode <schema.json> <hex>` — Decode hex-encoded protobuf bytes into JSON.
- `./pbcodec encode <schema.json> <data.json>` — Encode JSON data into hex-encoded protobuf bytes.
- `./pbcodec merge <schema.json> <hex1> <hex2>` — Merge two messages per protobuf merge semantics, output JSON.

Schema JSON format: `{"name":"...", "fields":[{"number":N, "name":"...", "type":"...", "repeated":bool, "packed":bool, "schema":{...}}]}`

Supported types: `int32`, `int64`, `uint32`, `uint64`, `sint32`, `sint64`, `bool`, `enum`, `fixed32`, `fixed64`, `sfixed32`, `sfixed64`, `float`, `double`, `string`, `bytes`, `message`, `group`.

The codec must conform to the Protocol Buffers wire format specification:

- **Tags**: `(field_number << 3) | wire_type` encoded as varint.
- **Wire types**: VARINT(0), I64(1), LEN(2), SGROUP(3), EGROUP(4), I32(5).
- **Varints**: Base-128 with MSB continuation bit, up to 10 bytes maximum; the 10th byte must be 0x00 or 0x01.
- **ZigZag**: `sint32`/`sint64` use ZigZag encoding for signed integers.
- **Fixed-width**: `fixed32`/`float` = 4 little-endian bytes; `fixed64`/`double` = 8 little-endian bytes (IEEE 754).
- **Length-delimited**: varint length prefix followed by payload for strings, bytes, submessages, and packed repeated fields.
- **Packed repeated**: multiple scalar values concatenated within one LEN record; all values must be decoded.
- **Groups**: SGROUP tag starts the group; EGROUP tag with matching field number ends it; unknown group fields must be skippable.
- **Merge semantics**: last-one-wins for scalars, recursive merge for submessages, concatenation for repeated fields.

Reference `.proto` definitions are at `/app/testdata/messages.proto`. The `protobuf-compiler` package (`protoc`) is pre-installed. Use `protoc --encode=MessageName -I/app/testdata messages.proto` (reads text-format from stdin, writes binary to stdout) and `protoc --decode_raw` (reads binary from stdin, writes decoded field dump to stdout) to cross-validate your codec's output against the canonical protobuf encoding.

Fix all bugs so the binary builds with `go build -o pbcodec .` in `/app/` and all encode, decode, and merge operations produce correct output conforming byte-for-byte to the canonical protobuf wire format.
