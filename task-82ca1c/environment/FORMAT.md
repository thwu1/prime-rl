# Summary-LSA Binary Format Specification

File: `/app/summary_lsas.bin`

Contains OSPFv2 Type-3 Summary-LSAs in a compact binary encoding. All multi-byte
integers are big-endian (network byte order). IPv4 addresses are stored as 4 raw
bytes in network byte order.

## File Header (11 bytes)

| Offset | Size | Description                                        |
|--------|------|----------------------------------------------------|
| 0      | 4    | Magic: ASCII `OSPF` (0x4F 0x53 0x50 0x46)         |
| 4      | 1    | Format version (0x01)                              |
| 5      | 4    | Area ID (IPv4)                                     |
| 9      | 2    | Record count *N* (uint16)                          |

## LSA Record (21 bytes each)

*N* records follow immediately after the header, starting at byte offset 11.

| Offset | Size | Description                                        |
|--------|------|----------------------------------------------------|
| 0      | 4    | LSA ID (IPv4 — destination network or host)        |
| 4      | 4    | Advertising Router (IPv4)                          |
| 8      | 4    | LS Sequence Number (uint32)                        |
| 12     | 2    | LS Age (uint16, seconds)                           |
| 14     | 4    | Network Mask (IPv4)                                |
| 18     | 3    | Metric (24-bit unsigned integer)                   |

The 24-bit metric is stored most-significant byte first. For example, a metric
of 10 is encoded as bytes `0x00 0x00 0x0A`.

Multiple records sharing the same LSA ID but different Advertising Router values
represent competing inter-area advertisements for the same destination.
