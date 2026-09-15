# MiniDB Binary Page Store Format (v1)

The page baseline store (`/app/pages.bin`) uses a packed binary representation for initial page state prior to any transaction activity.

## File Layout

    [HEADER: 8 bytes][ENTRY_0: 104 bytes][ENTRY_1: 104 bytes]...

## Header (8 bytes)

| Offset | Size | Type       | Description                    |
|--------|------|------------|--------------------------------|
| 0      | 4    | ASCII      | Magic: `PGST`                 |
| 4      | 2    | uint16 LE  | Format version (currently 1)   |
| 6      | 2    | uint16 LE  | Number of page entries         |

## Page Entry (104 bytes each)

| Offset | Size | Type       | Description                                  |
|--------|------|------------|----------------------------------------------|
| 0      | 4    | uint32 LE  | Page ID                                      |
| 4      | 4    | int32 LE   | Initial value (signed, two's complement)     |
| 8      | 32   | ASCII      | Table name (null-terminated, zero-padded)     |
| 40     | 64   | ASCII      | Description (null-terminated, zero-padded)    |

Entries are stored in ascending page ID order.
