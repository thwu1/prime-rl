Binary capture files at `/app/captures/` contain COBS-framed postcard-rpc messages from embedded device sessions. After COBS decoding, each frame consists of an 8-byte message type key, a varint sequence number, the serialized message body, and a trailing CRC-8 integrity byte (polynomial 0x31, init 0x00, no reflection). Some frames have been corrupted in transit and will fail CRC validation.

A prototype decoder at `/app/tools/buggy_decoder.py` was written from preliminary device-team notes (`/app/notes.md`) that contain several inaccuracies — the decoder has encoding bugs and lacks integrity checking. The canonical wire format specification is at `/app/spec.md`. Binary test vectors with manifest are at `/app/test_vectors/`. A reference encoder CLI is at `/app/reference/encode.py`. The protocol schema defining four message types is at `/app/schema.json`. Uncompiled C source for CRC-8 computation and frame validation is at `/app/tools/` with a Makefile.

Produce three output files:

`/app/frame_analysis.json` — Array of every frame across all sessions (valid and corrupt), ordered by session name (alphabetical) then wire position:

```json
[{"session": "<name>", "frame_index": 0, "crc_valid": true, "key_hex": "<8-byte key as 16-char hex>"}, ...]
```

`/app/decoded_messages.json` — Array of decoded messages from CRC-valid frames only, ordered by session name (alphabetical) then wire position:

```json
[{"session": "<name>", "seq_no": 42, "message_type": "MsgName", "body": {...}}, ...]
```

Enum variant representation: unit variant = `"VariantName"`, newtype variant = `{"VariantName": <value>}`, struct variant = `{"VariantName": {"field1": ..., "field2": ...}}`.

`/app/compatibility_report.json` — Ten schema migrations are described in `/app/migrations.json`. For each, determine whether data encoded under the current v1 schema can be correctly decoded by a decoder using the post-migration v2 schema (forward wire compatibility):

```json
[{"migration_id": "M1", "compatible": true}, {"migration_id": "M2", "compatible": false}, ...]
```