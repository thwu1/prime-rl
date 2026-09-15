An encrypted QUIC v1 client Initial packet captured from a test deployment is stored at `/app/capture/packet.hex` (hex-encoded raw bytes). Connection metadata including the Destination Connection ID is in `/app/capture/metadata.json`.

Your objective: build a Python module at `/app/quic_crypto.py` capable of decrypting QUIC Initial packets for both protocol versions, then use it to decrypt the captured packet.

## Module API (`/app/quic_crypto.py`)

The module must expose the following functions, supporting both QUIC v1 (version `0x00000001`) and QUIC v2 (version `0x6b3343cf`):

**`derive_initial_keys(dcid: bytes, version: int, perspective: str) -> dict`**
Derive the Initial packet protection keys from a Destination Connection ID for the given QUIC protocol version. `perspective` is `"client"` or `"server"`. Returns a dict with `"key"` (16 bytes), `"iv"` (12 bytes), and `"hp"` (16 bytes), all as `bytes`. Must produce correct results for any arbitrary DCID, not only specific test values.

**`remove_header_protection(packet: bytes, hp_key: bytes) -> tuple`**
Remove header protection from a complete QUIC long-header Initial packet. Returns `(unprotected_header_bytes, packet_number, pn_length, payload_start_offset)`. `pn_length` is the decoded packet number length (1–4 bytes), determined from the two least-significant bits of the unprotected first byte plus one. Must handle all valid packet number lengths.

**`decrypt_payload(encrypted_payload: bytes, packet_number: int, key: bytes, iv: bytes, header: bytes) -> bytes`**
Decrypt an AEAD-protected payload. `header` is the unprotected header bytes, used as additional authenticated data. Returns the decrypted plaintext.

**`parse_quic_varint(data: bytes, offset: int) -> tuple`**
Parse a QUIC variable-length integer starting at byte `offset`. Returns `(value, bytes_consumed)`. Must handle all four encoding sizes: 1-byte (6-bit value), 2-byte (14-bit), 4-byte (30-bit), and 8-byte (62-bit) per RFC 9000 Section 16.

**`parse_frames(payload: bytes) -> list`**
Parse all frames from decrypted payload bytes. Returns a list of dicts each containing a `"type"` key with the frame type name as a string. Required frame types:
- `"PADDING"` — frame type byte `0x00`
- `"PING"` — frame type byte `0x01`
- `"ACK"` — frame type byte `0x02` or `0x03`
- `"CRYPTO"` — frame type byte `0x06`; the dict must also include `"offset"` (int), `"length"` (int), and `"data"` (bytes) fields

## Captured Packet Decryption

Decrypt the packet at `/app/capture/packet.hex` using the DCID from `/app/capture/metadata.json`. The packet is a QUIC v1 client Initial. Write the result to `/app/capture/decrypted.json` as a JSON object:

```json
{"crypto_data": "<hex-encoded bytes of the data field from the first CRYPTO frame>"}
```

Python 3 and pip are available. Install any needed libraries.