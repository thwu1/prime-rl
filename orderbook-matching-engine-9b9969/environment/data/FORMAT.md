# Binary Wire Protocol Format

All multi-byte integers are big-endian. Trader names are UTF-8, right-padded with null bytes (`\x00`) to exactly 32 bytes.

## File Layout

| Field | Size | Description |
|-------|------|-------------|
| Magic | 4 bytes | ASCII `RTGX` |
| Config length | 4 bytes | uint32 — byte length of JSON config |
| Config | variable | UTF-8 JSON config object (same schema as JSON mode) |
| Messages | remainder | Concatenated message frames until EOF |

## Message Types

### Insert (tag = 0x01, 47 bytes total)

| Field | Offset | Size | Type |
|-------|--------|------|------|
| Tag | 0 | 1 | uint8 = 0x01 |
| Trader | 1 | 32 | UTF-8, null-padded |
| Order ID | 33 | 4 | uint32 |
| Side | 37 | 1 | uint8: 0 = SELL, 1 = BUY |
| Price | 38 | 4 | int32 |
| Volume | 42 | 4 | uint32 |
| Lifespan | 46 | 1 | uint8: 0 = FAK, 1 = GFD |

### Amend (tag = 0x02, 41 bytes total)

| Field | Offset | Size | Type |
|-------|--------|------|------|
| Tag | 0 | 1 | uint8 = 0x02 |
| Trader | 1 | 32 | UTF-8, null-padded |
| Order ID | 33 | 4 | uint32 |
| New Volume | 37 | 4 | uint32 |

### Cancel (tag = 0x03, 37 bytes total)

| Field | Offset | Size | Type |
|-------|--------|------|------|
| Tag | 0 | 1 | uint8 = 0x03 |
| Trader | 1 | 32 | UTF-8, null-padded |
| Order ID | 33 | 4 | uint32 |

### Snapshot (tag = 0x04, 1 byte)

| Field | Offset | Size | Type |
|-------|--------|------|------|
| Tag | 0 | 1 | uint8 = 0x04 |
