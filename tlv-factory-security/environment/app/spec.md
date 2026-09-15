# TLV Factory Data Format Specification v1

## Overview

This document specifies a Tag-Length-Value (TLV) binary format for storing
per-device factory data in embedded systems. The format supports cryptographic
signing (ECDSA-P256), device binding (SoC ID verification), and access control
via security policies. It is inspired by the barebox bootloader's TLV framework.

## Binary Format

A TLV blob consists of a fixed-size header, a variable-length payload of TLV
entries, and an optional signature block.

### Header (16 bytes, all fields little-endian)

| Offset | Size | Field         | Description                                    |
|--------|------|---------------|------------------------------------------------|
| 0      | 4    | magic         | Schema-specific identifier (uint32 LE)         |
| 4      | 2    | version       | Format version, must be `0x0001`               |
| 6      | 2    | flags         | Bit 0: blob is signed; Bit 1: device-bound     |
| 8      | 4    | payload_len   | Total byte length of all TLV entries (uint32)  |
| 12     | 4    | crc32         | IEEE CRC-32 computed over payload bytes only   |

### Payload

A sequence of TLV entries, each structured as:

| Offset | Size | Field  | Description                          |
|--------|------|--------|--------------------------------------|
| 0      | 2    | tag    | Field identifier (uint16 LE)         |
| 2      | 2    | length | Byte length of value (uint16 LE)     |
| 4      | N    | value  | Field data (N = length bytes)        |

TLV entries MUST be encoded in ascending order of tag number.

### Signature Block (present only when Flags bit 0 is set)

| Offset | Size | Field   | Description                              |
|--------|------|---------|------------------------------------------|
| 0      | 2    | sig_len | Byte length of signature (uint16 LE)     |
| 2      | S    | sig     | DER-encoded ECDSA-P256/SHA-256 signature |

The signature covers all bytes preceding the signature block (header + payload).

### Blob Size

Total blob size = 16 + payload_len [+ 2 + sig_len if signed].

## Field Types

Each field in a schema has a type that governs binary encoding:

| Type     | Binary Encoding                    | JSON Representation              |
|----------|------------------------------------|----------------------------------|
| `string` | UTF-8 bytes (no null terminator)   | JSON string                      |
| `mac`    | 6 raw bytes                        | `"AA:BB:CC:DD:EE:FF"` (uppercase)|
| `hex`    | Raw bytes                          | `"0x..."` prefix, uppercase hex  |
| `uint16` | 2 bytes, little-endian             | JSON integer                     |
| `uint32` | 4 bytes, little-endian             | JSON integer                     |
| `binary` | Raw bytes                          | Base64-encoded string            |

## Schema Format (YAML)

```yaml
magic: 0xF0CAD001       # uint32 magic identifying this schema
name: "board-factory-v1" # human-readable name
fields:
  - tag: 0x0001
    name: "serial_number"
    type: "string"
    required: true
  - tag: 0x0002
    name: "mac_address"
    type: "mac"
    required: true
  - tag: 0x0003
    name: "soc_id"
    type: "hex"
    device_bind: true    # this field is used for device binding
    required: false
```

`device_bind: true` marks a field whose value is compared against the
device's SoC ID during device-binding verification.

## Signing

1. Build the unsigned blob (header with Flags bit 0 = 0, plus payload).
2. To sign: set Flags bit 0 to 1 in the header, then compute
   `ECDSA-P256(SHA-256(header || payload))` using the private key.
3. Append the signature block: 2-byte sig_len (LE) + DER signature bytes.

When signing a pre-existing unsigned blob via the `sign` subcommand, the
tool must update the flags field in the header to set bit 0, then sign the
resulting header+payload, then append the signature block.

## Verification

1. Parse header; confirm Flags bit 0 is set.
2. Read payload (payload_len bytes after header).
3. Verify CRC-32 of payload matches header's crc32 field.
4. Extract signature block from after payload.
5. Verify `ECDSA-P256(SHA-256(header || payload))` against the public key.

## Device Binding

When `--bind-soc-id` is given during decode:
1. Confirm Flags bit 1 (device-bound) is set.
2. Find the schema field with `device_bind: true`.
3. Compare its decoded value against the provided SoC ID (case-insensitive hex).
4. Reject the blob if they differ.

## Security Policies (YAML)

```yaml
name: "lockdown"
priority: 100
rules:
  allow_unsigned: false
  allow_unbound_device: false
  visible_fields:
    - "serial_number"
    - "mac_address"
  writable: false
transitions_from:
  - "development"
  - "factory"
```

### Policy Enforcement (`policy-filter`)

1. If `allow_unsigned` is false and the blob is not signed, reject (exit 2).
2. If `allow_unbound_device` is false and the blob is not device-bound, reject (exit 2).
3. Decode all fields.
4. Return only fields listed in `visible_fields`. If `visible_fields` is the
   string `"all"`, return all fields.

### Policy Transitions (`policy-transition`)

A transition from policy A to policy B is valid if and only if:
1. B's priority >= A's priority.
2. A's name appears in B's `transitions_from` list.

If invalid, exit with code 3.

## CLI Interface

```
python3 /app/tlv_manager.py encode --schema SCHEMA --data DATA --output OUTPUT [--sign-key KEY]
python3 /app/tlv_manager.py decode --schema SCHEMA --input INPUT [--verify-key KEY] [--bind-soc-id SOC_ID]
python3 /app/tlv_manager.py sign --input INPUT --key KEY --output OUTPUT
python3 /app/tlv_manager.py verify --input INPUT --key KEY
python3 /app/tlv_manager.py policy-filter --schema SCHEMA --input INPUT --policy POLICY [--verify-key KEY]
python3 /app/tlv_manager.py policy-transition --from-policy FROM --to-policy TO --policy-dir DIR
```

### Exit Codes

| Code | Meaning                                                |
|------|--------------------------------------------------------|
| 0    | Success                                                |
| 1    | General error (missing files, bad arguments, etc.)     |
| 2    | Verification/validation failure (bad sig, CRC, magic)  |
| 3    | Policy violation (denied transition)                   |

### Output

- `encode`: writes binary blob to --output path
- `decode`: prints JSON to stdout
- `sign`: writes signed blob to --output path
- `verify`: prints status message, exits 0 or 2
- `policy-filter`: prints filtered JSON to stdout
- `policy-transition`: prints status message, exits 0 or 3
