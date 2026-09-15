# Speed Daemon Binary Protocol Specification


## Overview

The Speed Daemon system enforces average speed limits across a road network. A central server accepts TCP connections from two types of clients:

- **Cameras**: positioned on roads, report license plate sightings with timestamps
- **Ticket dispatchers**: responsible for certain roads, receive speeding tickets

When a car is observed at two cameras on the same road, and its average speed exceeds the limit, the server generates a ticket and sends it to a dispatcher for that road.

The server must support at least 150 simultaneous TCP connections on port 9000.

## Data Types

All multi-byte integers are big-endian (network byte order).

| Type | Size | Description |
|------|------|-------------|
| `u8` | 1 byte | Unsigned 8-bit integer |
| `u16` | 2 bytes | Unsigned 16-bit integer |
| `u32` | 4 bytes | Unsigned 32-bit integer |
| `str` | 1 + N bytes | A `u8` length prefix followed by that many bytes of ASCII data |

Examples:

    u8:   20          → 32
    u16:  00 7b       → 123
    u32:  00 01 e2 40 → 123456
    str:  04 55 4e 31 58 → "UN1X"

## Message Format

Messages are concatenated directly on the TCP stream with **no padding, delimiters, or framing**. Each message begins with a single `u8` type byte, followed by the fields defined for that type. Field names are not transmitted; fields are identified solely by position.

It is an error for a client to send a message type not listed as Client→Server below.

## Message Types

### `0x10`: Error (Server → Client)

| Field | Type |
|-------|------|
| msg | str |

Sent when the client makes a protocol error. The server must disconnect the client immediately after sending this message.

    10 03 62 61 64    →  Error{msg: "bad"}

### `0x20`: Plate (Client → Server)

| Field | Type |
|-------|------|
| plate | str |
| timestamp | u32 |

Reports that this camera observed the given license plate at the given timestamp (Unix time, unsigned seconds since epoch). Only valid from clients identified as cameras.

Cameras may send observations in any order and with any delay. Do not assume observations arrive in timestamp order, even from the same camera.

    20 04 55 4e 31 58 00 00 03 e8    →  Plate{plate: "UN1X", timestamp: 1000}

### `0x21`: Ticket (Server → Client)

| Field | Type |
|-------|------|
| plate | str |
| road | u16 |
| mile1 | u16 |
| timestamp1 | u32 |
| mile2 | u16 |
| timestamp2 | u32 |
| speed | u16 |

Sent to a dispatcher when a speed violation is detected. `mile1`/`timestamp1` refer to the earlier observation (smaller timestamp). `mile2`/`timestamp2` refer to the later observation. `speed` is the average speed multiplied by 100, as an integer (e.g., 8000 means 80.00 mph).

    21 04 55 4e 31 58 00 7b 00 08 00 00 00 00 00 09 00 00 00 2d 1f 40
    →  Ticket{plate: "UN1X", road: 123, mile1: 8, timestamp1: 0, mile2: 9, timestamp2: 45, speed: 8000}

### `0x40`: WantHeartbeat (Client → Server)

| Field | Type |
|-------|------|
| interval | u32 |

Requests periodic heartbeat messages at the given interval, specified in **deciseconds** (10ths of a second). An interval of 25 means one heartbeat every 2.5 seconds. An interval of 0 means no heartbeats (the default).

It is an error to send WantHeartbeat more than once on a single connection.

    40 00 00 00 0a    →  WantHeartbeat{interval: 10}

### `0x41`: Heartbeat (Server → Client)

No fields. Sent at the interval requested by the client's WantHeartbeat message.

    41    →  Heartbeat{}

### `0x80`: IAmCamera (Client → Server)

| Field | Type |
|-------|------|
| road | u16 |
| mile | u16 |
| limit | u16 |

Identifies this client as a camera at the given mile position on the given road, with the given speed limit in miles per hour. All cameras on the same road have the same speed limit.

It is an error if the client has already identified as a camera or dispatcher.

    80 00 7b 00 08 00 3c    →  IAmCamera{road: 123, mile: 8, limit: 60}

### `0x81`: IAmDispatcher (Client → Server)

| Field | Type |
|-------|------|
| numroads | u8 |
| roads | numroads × u16 |

Identifies this client as a ticket dispatcher for the listed roads.

It is an error if the client has already identified as a camera or dispatcher.

    81 03 00 42 01 70 13 88    →  IAmDispatcher{roads: [66, 368, 5000]}

## Speed Enforcement Rules

### Speed Calculation

When a car is observed at two different cameras on the same road:

    speed (mph) = |mile2 - mile1| / |timestamp2 - timestamp1| × 3600

A ticket **must** be issued if the speed exceeds the road's limit by 0.5 mph or more. A ticket **must never** be issued if the speed is below the limit. For speeds between the limit and limit + 0.5 mph, ticketing is optional.

Check all pairs of observations for the same car on the same road, not just adjacent cameras. A car may skip intermediate cameras.

### One Ticket Per Car Per Day

The server may issue **at most one ticket per car per day**, across all roads.

Days are defined as `floor(timestamp / 86400)`. A ticket that spans from day D1 to day D2 (where D1 = floor(timestamp1 / 86400) and D2 = floor(timestamp2 / 86400)) applies to **every day in the range [D1, D2]**. No further ticket may be issued for that car on any of those days.

### Ticket Dispatching

When a ticket is generated, send it to a connected dispatcher for that road. If multiple dispatchers serve the same road, choose one arbitrarily but **never send the same ticket twice**.

If **no dispatcher** is connected for the road, **queue the ticket** and deliver it when a dispatcher for that road connects.

If a ticket is sent but the dispatcher disconnects before receiving it, the ticket is lost.

### Rounding

The speed field in a Ticket is `round(speed_mph * 100)`, expressed as a `u16` integer.

## Error Conditions

The following are protocol errors. On error, the server must send an Error message and disconnect:

- Client sends a Plate message before identifying as a camera
- Client sends IAmCamera or IAmDispatcher after already identifying
- Client sends WantHeartbeat more than once
- Client sends an unknown message type

## Example Session

Three clients connect. Clients 1 and 2 are cameras on road 123 (60 mph limit). Client 3 is a dispatcher for road 123. Car "UN1X" travels 1 mile in 45 seconds (80 mph), exceeding the limit.

**Client 1** (camera at mile 8):

    → IAmCamera{road: 123, mile: 8, limit: 60}
    → Plate{plate: "UN1X", timestamp: 0}

**Client 2** (camera at mile 9):

    → IAmCamera{road: 123, mile: 9, limit: 60}
    → Plate{plate: "UN1X", timestamp: 45}

**Client 3** (dispatcher for road 123):

    → IAmDispatcher{roads: [123]}
    ← Ticket{plate: "UN1X", road: 123, mile1: 8, timestamp1: 0, mile2: 9, timestamp2: 45, speed: 8000}
