
# XPROTO Binary Protocol Specification v1.0

## Overview

XPROTO is a TLV-based binary protocol with integrity checking and optional compression.

## Message Layout

```
Offset   Size   Field
─────────────────────────────────────
0        4      Magic: 0x58 0x50 0x52 0x01 ("XPR\x01")
4        2      Version: uint16_le (valid values: 1, 2, 3)
6        2      Flags: uint16_le (bitfield, see below)
8        4      Payload Length: uint32_le (byte count of payload)
12       N      Payload: sequence of TLV entries (N = Payload Length)
12+N     4      CRC32: uint32_le, IEEE 802.3 CRC over bytes [0, 12+N)
```

Total message size = 12 + Payload Length + 4

## Flags

| Bit | Mask   | Name               | Description |
|-----|--------|--------------------|-------------|
| 0   | 0x0001 | COMPRESSED         | Payload is zlib-compressed. Decompress before parsing TLV entries. |
| 1   | 0x0002 | CHECKSUM_REQUIRED  | CRC32 must be valid. If unset, CRC field is ignored during validation. |
| 2   | 0x0004 | EXTENDED           | Reserved for version 3 extensions. If set, version must be >= 3. |

## TLV Entry Format

Each entry within the payload:

```
Offset   Size   Field
─────────────────────────────────
0        1      Type: uint8
1        2      Length: uint16_le (byte count of Value field)
3        L      Value: L = Length bytes
```

Entry size = 3 + Length

## TLV Types

| Type | ID   | Min Version | Value Format |
|------|------|-------------|--------------|
| STRING | 0x01 | 1 | L bytes of valid UTF-8 text |
| INT32  | 0x02 | 1 | Exactly 4 bytes, uint32_le |
| NESTED | 0x03 | 2 | Value contains a sequence of sub-TLV entries |
| ARRAY  | 0x04 | 2 | First byte = count (uint8), followed by count × 4-byte uint32_le values |
| KEYVAL | 0x05 | 3 | First byte = key_len (uint8), next key_len bytes = key, remaining bytes = value |

## Constraints

- Payload Length must exactly match the sum of all TLV entry sizes (3 + Length for each).
- Maximum nesting depth for NESTED entries: 4 levels.
- Maximum TLV entries per level: 32.
- STRING values must be valid UTF-8.
- INT32 Length field must be exactly 4.
- ARRAY: count × 4 must equal Length − 1.
- KEYVAL: key_len + 1 must not exceed Length.
- TLV types are version-gated: using a type below its minimum version is invalid.
- EXTENDED flag (bit 2) requires version >= 3.
- If COMPRESSED flag is set, the stored payload bytes are the zlib-compressed form of the actual TLV data.
- CRC32 is computed over the raw message bytes from offset 0 through 12 + Payload Length − 1 (i.e., header + raw payload, before any decompression).

## Processing Order

**Construction:** Serialize TLV entries → (optionally) zlib-compress → write header with payload length → compute CRC32 over [header + payload] → append CRC32.

**Parsing:** Validate magic/version → read header → verify CRC32 (if CHECKSUM_REQUIRED) → (optionally) decompress payload → parse TLV entries.
