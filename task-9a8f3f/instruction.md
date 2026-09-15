An embedded sensor network exchanges data over serial links using a compact binary serialization protocol with a byte-stuffing framing layer. The Rust firmware implementation is at `/app/firmware/` — the serializer (`ser.rs`), deserializer (`deser.rs`), framing module (`framing.rs`), and device type definitions (`types.rs`) together define the complete wire protocol. A JSON schema at `/app/schema.json` describes the device's type system.

A compiled C reference encoder/decoder is at `/app/reference/cobs_ref`. It supports `encode` and `decode` modes via stdin/stdout (e.g., `printf '\x01\x02\x03' | /app/reference/cobs_ref encode | xxd`). Pre-generated binary test vector files are at `/app/vectors/cobs_vectors.bin` (paired original/encoded data) and `/app/vectors/framed_stream.bin` (a framed multi-message stream). Use `xxd` to inspect these binary files and the C reference binary to cross-validate your implementation.

Build `/app/postcard_codec.py`: a Python module that faithfully reproduces the wire-format behavior of the Rust firmware. Study the Rust source code to understand each encoding layer and its edge cases. The module must export these functions:

- `varint_encode(value, type_bits) -> bytes` — encode an unsigned integer using the variable-length integer scheme from the Rust serializer. `type_bits` is the integer width (16, 32, 64, 128).
- `varint_decode(data, type_bits) -> (value, bytes_consumed)` — decode a varint. Must reject overlong and out-of-range encodings (raising `ValueError`).
- `zigzag_encode(value) -> int` — apply the signed-to-unsigned mapping used by the Rust serializer for signed integers.
- `zigzag_decode(value) -> int` — reverse the mapping.
- `cobs_encode(data) -> bytes` — encode using the byte-stuffing algorithm from the Rust framing module. Output must contain no 0x00 bytes.
- `cobs_decode(data) -> bytes` — decode byte-stuffed data.
- `serialize(schema, type_name, data) -> bytes` — schema-driven serialization matching the Rust implementation's wire format for all types defined in `schema.json` (structs, enums with all variant kinds, tuple structs, sequences, maps, strings, bytes, options, and all primitive types).
- `deserialize(schema, type_name, data) -> (value, bytes_consumed)` — schema-driven deserialization, inverse of serialize.
- `frame_messages(messages) -> bytes` — frame multiple messages for serial transmission using the framing scheme from `framing.rs`.
- `unframe_messages(stream) -> list[bytes]` — recover individual messages from a framed byte stream.
- `is_canonical_varint(data, type_bits) -> bool` — determine whether a varint encoding is in canonical (minimal) form.
- `max_varint_len(type_bits) -> int` — return the maximum varint encoded length in bytes for the given bit width.

The test suite validates against the Rust-derived test vectors, hand-computed expected byte sequences, the compiled C reference binary, and the pre-generated binary vector files.