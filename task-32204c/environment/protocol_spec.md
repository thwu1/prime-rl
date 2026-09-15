# Market Data Feed Protocol Specification

## Overview

Market data is delivered via UDP multicast. Each UDP packet contains a **channel header** followed by one or more **XMBO records**. Two channels carry the data:

- **Channel A** (primary): carries all instruments
- **Channel B** (backup): carries a partial duplicate of Channel A for redundancy

The reference database at `/app/data/instruments.db` (SQLite) contains instrument metadata, channel configuration, and gap recovery policies. Query it for instrument details (tick sizes, price scaling, session times) and channel port mappings.

## Capture Format

The raw network capture is stored as a standard pcap file at `/app/data/market_feed.pcap`. It contains the UDP multicast packets plus unrelated network traffic (ARP, ICMP) that must be filtered out.

## UDP Payload Structure

Each UDP payload begins with an 8-byte **channel header**, followed by the message records:

    [channel_header (8 bytes)][record_0 (64 bytes)][record_1]...[record_{n-1}]

### Channel Header (8 bytes)

All multi-byte integers are **little-endian**.

| Offset | Size | Type   | Description                       |
|--------|------|--------|-----------------------------------|
| 0      | 2    | uint16 | Channel ID (1 = A, 2 = B)        |
| 2      | 4    | uint32 | Channel sequence start            |
| 6      | 2    | uint16 | Message count (records in packet) |

The `channel_sequence_start` is the channel-level sequence number of the first record in this packet. Channel sequence numbers are per-channel and increment independently from the record-level sequence numbers.

## XMBO Record Layout (64 bytes)

| Offset | Size | Type     | Description                                      |
|--------|------|----------|--------------------------------------------------|
| 0      | 8    | uint64   | Event timestamp (nanoseconds since midnight UTC) |
| 8      | 8    | uint64   | Order ID                                         |
| 16     | 8    | int64    | Price (fixed-point, see below)                   |
| 24     | 4    | uint32   | Size / Quantity                                  |
| 28     | 1    | uint8    | Action code (see below)                          |
| 29     | 1    | uint8    | Side code (see below)                            |
| 30     | 2    | uint16   | Flags (bitfield)                                 |
| 32     | 8    | uint64   | Record sequence number (global ordering key)     |
| 40     | 4    | uint32   | Instrument ID                                    |
| 44     | 20   | bytes    | Reserved (zero-filled)                           |

### Price Encoding

Prices are **signed 64-bit integers** (int64) in fixed-point representation. The scale factor is stored per-instrument in the `price_scale` column of the `instruments` table in the reference database. To convert:

    price_float = raw_int64_value / price_scale

### Action Codes

| Byte | ASCII | Meaning                                          |
|------|-------|--------------------------------------------------|
| 0x41 | 'A'   | **Add** — new order placed in the book           |
| 0x43 | 'C'   | **Cancel** — order removed (size field ignored)  |
| 0x4D | 'M'   | **Modify** — price and/or size updated           |
| 0x54 | 'T'   | **Trade** — partial fill (size = fill quantity)   |
| 0x46 | 'F'   | **Fill** — complete fill, order removed           |

### Side Codes

| Byte | ASCII | Meaning        |
|------|-------|----------------|
| 0x42 | 'B'   | Bid (buy)      |
| 0x53 | 'S'   | Ask (sell)     |

### Flags

| Bit | Mask   | Meaning                         |
|-----|--------|---------------------------------|
| 0   | 0x0001 | Last message in event group     |
| 2   | 0x0004 | Snapshot (initial book state)   |

## Message Semantics

### Add (0x41)
New order placed. The `order_id`, `price`, `size`, `side`, and `instrument_id` define it. Snapshot-flagged Adds represent initial book state.

### Cancel (0x43)
Order removed from book. Identified by `order_id`. The `size` field should be ignored.

### Modify (0x4D)
Order's price and/or size updated to the values in the record. If the price changed, the order loses time priority.

### Trade (0x54)
Partial execution. The `size` field is the **fill quantity** (not remaining). The resting order's remaining size decreases by this amount. Generates trade volume.

### Fill (0x46)
Complete execution removing the order. The `size` field is the **final fill quantity**. Generates trade volume.

## Sequencing and Deduplication

Records have a **record-level sequence number** (offset 32) that defines the global processing order across all instruments and channels. Both channels may carry the same records; **deduplicate by record sequence number** before processing. Records must be sorted by this sequence number (ascending) to reconstruct correct book state.

Channel-level sequence numbers (in the channel header) are independent and only useful for **gap detection** within a channel.

## Gap Detection

Compare consecutive channel-level sequence numbers within each channel. If `expected_next = prev_start + prev_count` does not equal the next packet's `channel_sequence_start`, a gap exists. The `gap_recovery` table in the reference database indicates tolerance thresholds.

## Iceberg Reload Detection

An **iceberg reload** is detected when:
1. A Fill ('F') event at price P, side S, timestamp T_fill is followed by
2. An Add ('A') event at the **same price P, same side S, same instrument** at timestamp T_add
3. Where T_add - T_fill ≤ 100,000 nanoseconds (100 µs)

Each Fill can trigger at most one iceberg detection.

## Required Output

Build a SQLite database at `/app/output/analysis.db` with these tables:

### Table: `metrics`
Per-instrument summary analytics.

| Column          | Type  | Description                                                 |
|-----------------|-------|-------------------------------------------------------------|
| instrument_id   | INT   | Instrument ID                                               |
| symbol          | TEXT  | Symbol from reference database                              |
| vwap            | REAL  | Volume-weighted average price (Trade + Fill events)         |
| total_volume    | INT   | Sum of fill quantities across all Trade and Fill events     |
| trade_count     | INT   | Count of Trade + Fill events                                |
| max_spread      | REAL  | Maximum best_ask - best_bid observed (when both sides exist)|
| iceberg_count   | INT   | Iceberg reload detections                                   |
| final_best_bid  | REAL  | Best bid after all messages (NULL if none)                  |
| final_best_ask  | REAL  | Best ask after all messages (NULL if none)                  |
| final_bid_size  | INT   | Total quantity at best bid                                  |
| final_ask_size  | INT   | Total quantity at best ask                                  |
| bid_depth       | INT   | Distinct bid price levels remaining                         |
| ask_depth       | INT   | Distinct ask price levels remaining                         |
| message_count   | INT   | Total records processed for this instrument                 |

### Table: `trades`
One row per Trade or Fill event.

| Column        | Type | Description                          |
|---------------|------|--------------------------------------|
| instrument_id | INT  | Instrument ID                        |
| timestamp_ns  | INT  | Event timestamp (ns since midnight)  |
| price         | REAL | Execution price                      |
| quantity      | INT  | Fill quantity                        |
| side          | TEXT | 'B' or 'S'                          |
| action        | TEXT | 'T' or 'F'                          |
| sequence      | INT  | Record sequence number               |

### Table: `gaps`
Detected sequence gaps in channel-level sequences.

| Column       | Type | Description                           |
|--------------|------|---------------------------------------|
| channel_id   | INT  | Channel ID (1 or 2)                   |
| expected_seq | INT  | Expected channel sequence number      |
| actual_seq   | INT  | Actual channel sequence number seen   |
| gap_size     | INT  | Number of missing channel sequences   |

### Table: `latency`
Per-packet capture latency analysis.

| Column          | Type | Description                                           |
|-----------------|------|-------------------------------------------------------|
| channel_id      | INT  | Channel ID                                            |
| capture_epoch_us| INT  | Packet capture time (microseconds since Unix epoch)   |
| message_time_ns | INT  | First record's event timestamp (ns since midnight)    |
| packet_msg_count| INT  | Number of records in the packet                       |
