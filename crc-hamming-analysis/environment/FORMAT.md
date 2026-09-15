# Binary Test Data Format

File: `test_data.bin`

## Header

| Offset | Size | Type     | Description                                      |
|--------|------|----------|--------------------------------------------------|
| 0      | 4    | char[4]  | Magic bytes: ASCII `CRC8` (0x43 0x52 0x43 0x38)  |
| 4      | 1    | uint8    | Format version (currently 1)                     |
| 5      | 1    | uint8    | Number of test vectors (N)                       |

## Test Vectors (repeated N times, starting at offset 6)

| Field       | Size        | Type      | Description                          |
|-------------|-------------|-----------|--------------------------------------|
| name_length | 1           | uint8     | Length of vector name in bytes       |
| name        | name_length | char[]    | ASCII vector name                    |
| data_length | 2           | uint16 BE | Length of payload data (big-endian)  |
| data        | data_length | uint8[]   | Raw payload bytes                    |

Vectors are packed sequentially with no alignment or padding between them.
