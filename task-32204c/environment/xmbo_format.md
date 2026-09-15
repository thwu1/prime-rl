# XMBO Binary Format Specification v2

## Overview

The XMBO format stores Market-by-Order (MBO) tick data in a compact binary encoding.
All multi-byte integers use **little-endian** byte order.

## File Structure

    [header (48 bytes)][record_0 (64 bytes)][record_1]...[record_{n-1}]

Total file size = 48 + (64 x num_records) bytes.

## Header Layout (48 bytes)

| Offset | Size | Type     | Description                                      |
|--------|------|----------|--------------------------------------------------|
| 0      | 4    | char[4]  | Magic bytes: `XMBO` (0x58 0x4D 0x42 0x4F)       |
| 4      | 2    | uint16   | Format version (currently 2)                     |
| 6      | 2    | uint16   | Header size in bytes (48)                        |
| 8      | 2    | uint16   | Record size in bytes (64)                        |
| 10     | 2    | uint16   | Reserved (0)                                     |
| 12     | 4    | uint32   | Number of records in the file                    |
| 16     | 4    | uint32   | Instrument ID                                    |
| 20     | 12   | char[12] | Symbol (null-padded ASCII)                       |
| 32     | 8    | uint64   | Session start timestamp (nanoseconds since midnight UTC) |
| 40     | 8    | uint64   | Session end timestamp (nanoseconds since midnight UTC)   |

## Record Layout (64 bytes)

| Offset | Size | Type     | Description                                      |
|--------|------|----------|--------------------------------------------------|
| 0      | 8    | uint64   | Event timestamp (nanoseconds since midnight UTC) |
| 8      | 8    | uint64   | Order ID                                         |
| 16     | 8    | int64    | Price (fixed-point encoding, see below)          |
| 24     | 4    | uint32   | Size / Quantity                                  |
| 28     | 1    | uint8    | Action code (see below)                          |
| 29     | 1    | uint8    | Side code (see below)                            |
| 30     | 2    | uint16   | Flags (bitfield, see below)                      |
| 32     | 8    | uint64   | Sequence number                                  |
| 40     | 24   | bytes    | Reserved (zero-filled)                           |

## Price Encoding

Prices are stored as **signed 64-bit integers** in fixed-point representation
with a scale factor of 10^9 (nine implied decimal places).

To convert the raw int64 value to a floating-point price:

    price_float = raw_int64_value / 1,000,000,000

Example: A price of $4500.25 is stored as the integer value 4500250000000
(i.e., 4500.25 multiplied by 10^9).

The field is signed (`int64`, not `uint64`) to support instruments that can
have negative prices such as calendar spreads.

## Action Codes

| Byte Value | ASCII | Meaning                                            |
|------------|-------|----------------------------------------------------|
| 0x41       | 'A'   | **Add** - New order added to the book               |
| 0x43       | 'C'   | **Cancel** - Existing order removed from the book   |
| 0x4D       | 'M'   | **Modify** - Existing order's price/size changed    |
| 0x54       | 'T'   | **Trade** - Partial execution against resting order |
| 0x46       | 'F'   | **Fill** - Complete execution, order fully consumed |

## Side Codes

| Byte Value | ASCII | Meaning          |
|------------|-------|------------------|
| 0x42       | 'B'   | Bid (buy side)   |
| 0x53       | 'S'   | Ask (sell side)  |

## Flags Bitfield

| Bit | Mask   | Meaning                         |
|-----|--------|---------------------------------|
| 0   | 0x0001 | Last message in the event group |
| 2   | 0x0004 | Snapshot (initial book state)   |

## Message Semantics

### Add (0x41)
A new order is placed in the book. Fields `order_id`, `price`, `size`, and `side`
define the order. If the snapshot flag (bit 2) is set, this message is part of the
initial book state reconstruction.

### Cancel (0x43)
An existing order is removed from the book. The `order_id` identifies the order.
The `size` field should be ignored for Cancel messages. The `price` and `side`
fields reflect the cancelled order's original values.

### Modify (0x4D)
An existing order's attributes are updated. The `price` and `size` fields contain
the **new** values after modification. The `order_id` identifies which order to
modify. If the price has changed from the order's previous price, the order loses
its time priority (semantically equivalent to a cancel and re-add).

### Trade (0x54)
A partial execution against a resting order. The `size` field is the **fill quantity**
(the number of units that were executed), not the remaining quantity. The resting
order's remaining size decreases by this fill quantity. The `price` field is the
execution price. This message generates trade volume.

### Fill (0x46)
A complete execution that removes the order from the book. The `size` field is the
**final fill quantity** (which equals the order's remaining size before this event).
The `price` field is the execution price. This message generates trade volume.

## Sequencing

Records in the file **may not be ordered** by timestamp or sequence number due to
multi-channel feed delivery. Consumers must sort records by the `sequence` field
(ascending) before processing to reconstruct correct book state.
