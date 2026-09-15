# MBO Record Schema

Market-by-Order (MBO) records capture individual order-level events from an
exchange feed. Each record consists of a header followed by order-specific fields.

## Record Header

| Field         | Rust Type | Description                                          |
|---------------|-----------|------------------------------------------------------|
| length        | u8        | Record length in 32-bit words                        |
| rtype         | u8        | Record type identifier (MBO = 0xA0)                  |
| publisher_id  | u16       | Publisher/venue identifier                           |
| instrument_id | u32       | Numeric instrument identifier                        |
| ts_event      | u64       | Exchange timestamp, nanoseconds since UNIX epoch     |

## MBO Body Fields

| Field       | Rust Type | Description                                            |
|-------------|-----------|--------------------------------------------------------|
| order_id    | u64       | Venue-assigned order identifier                        |
| price       | i64       | Order price in fixed-point encoding (see prices.md)    |
| size        | u32       | Order quantity                                         |
| flags       | u8        | Event flags bitfield                                   |
| channel_id  | u8        | Channel identifier (0-indexed)                         |
| action      | c_char    | Event action type (see actions.md)                     |
| side        | c_char    | Order side (see actions.md)                            |
| ts_recv     | u64       | Capture server receive timestamp (nanoseconds)         |
| ts_in_delta | i32       | Offset from ts_recv to exchange send time (nanoseconds)|
| sequence    | u32       | Venue-assigned message sequence number                 |
