# Speed Enforcement Protocol Specification

## Overview

You are building a server to coordinate enforcement of **average speed limits** on a road network.

Your server handles two types of client: *cameras* and *ticket dispatchers*.

Clients connect over TCP and speak a protocol using a **binary format**. Support at least 150 simultaneous clients.

### Cameras

Each *camera* is on a specific road, at a specific location (mile marker), and has a specific speed limit. Each camera provides this information when it connects. Cameras report each number plate observed, along with the timestamp of observation. Timestamps are unsigned Unix timestamps (seconds since 1970-01-01). Cameras may send observations in **any order** and with **any delay**.

### Ticket Dispatchers

Each *ticket dispatcher* is responsible for some number of roads. When the server detects that a car's average speed exceeded the limit between 2 observations on the same road, it finds a responsible dispatcher and sends it a ticket.

### Roads

Each road is identified by a number from 0 to 65535. A single road has the same speed limit everywhere. Positions are measured in miles from the start of the road (exact integers).

### Cars

Each car has a number plate represented as an uppercase alphanumeric ASCII string.

## Data Types

### `u8`, `u16`, `u32`

Unsigned integers of 8, 16, and 32 bits, transmitted in **network byte-order (big endian)**.

    Type | Hex data    | Value
    -------------------------------
    u8   |          20 |         32
    u16  |       00 20 |         32
    u16  |       12 45 |       4677
    u32  | 00 00 00 20 |         32
    u32  | 00 00 12 45 |       4677

### `str`

A **length-prefixed** string. A single `u8` containing the string's length (0-255), followed by that many bytes of ASCII.

    Type | Hex data                   | Value
    ----------------------------------------------
    str  | 00                         | ""
    str  | 03 66 6f 6f                | "foo"
    str  | 08 45 6C 62 65 72 65 74 68 | "Elbereth"

## Message Types

Each message starts with a **single `u8` specifying the message type**. This is followed by the message contents. **Field names are not transmitted** -- fields are identified by position. Messages are concatenated with **no padding or delimiters**.

It is an error for a client to send a message type not listed as "Client->Server" below.

### `0x10`: Error (Server->Client)

Fields:

- `msg: str`

When the client does something the protocol declares "an error", the server must send an `Error` message and **immediately disconnect** that client.

    Hexadecimal:                            Decoded:
    10                                      Error{
    03 62 61 64                                 msg: "bad"
                                            }

### `0x20`: Plate (Client->Server)

Fields:

- `plate: str`
- `timestamp: u32`

Reports that this camera observed the given plate at its location at the given timestamp. Observations may arrive in any temporal order.

It is an error for a client that has not identified itself as a camera to send a `Plate` message.

    Hexadecimal:                Decoded:
    20                          Plate{
    04 55 4e 31 58                  plate: "UN1X",
    00 00 03 e8                     timestamp: 1000
                                }

### `0x21`: Ticket (Server->Client)

Fields:

- `plate: str`
- `road: u16`
- `mile1: u16`
- `timestamp1: u32`
- `mile2: u16`
- `timestamp2: u32`
- `speed: u16` (100x miles per hour)

When the server detects a speed violation between 2 observations, it generates a Ticket. `mile1`/`timestamp1` must refer to the **earlier** observation (smaller timestamp), `mile2`/`timestamp2` to the **later** one. The `speed` field is the average speed **multiplied by 100**, expressed as an integer.

    Hexadecimal:            Decoded:
    21                      Ticket{
    04 55 4e 31 58              plate: "UN1X",
    00 7b                       road: 123,
    00 08                       mile1: 8,
    00 00 00 00                 timestamp1: 0,
    00 09                       mile2: 9,
    00 00 00 2d                 timestamp2: 45,
    1f 40                       speed: 8000,
                            }

### `0x40`: WantHeartbeat (Client->Server)

Fields:

- `interval: u32` (deciseconds)

Requests periodic heartbeats. The server must send `Heartbeat` messages at the given interval, specified in **deciseconds** (10 per second). An interval of `25` means every 2.5 seconds. An interval of `0` means no heartbeats (the default).

It is an error for a client to send multiple `WantHeartbeat` messages on a single connection.

    Hexadecimal:    Decoded:
    40              WantHeartbeat{
    00 00 00 0a         interval: 10
                    }

### `0x41`: Heartbeat (Server->Client)

No fields. A single byte `0x41`. Sent at the interval requested by WantHeartbeat.

    Hexadecimal:    Decoded:
    41              Heartbeat{}

### `0x80`: IAmCamera (Client->Server)

Fields:

- `road: u16`
- `mile: u16`
- `limit: u16` (miles per hour)

Identifies this client as a camera on the given road, at the given mile, with the given speed limit.

It is an error for a client that has already identified itself (as either camera or dispatcher) to send this message.

    Hexadecimal:    Decoded:
    80              IAmCamera{
    00 7b               road: 123,
    00 08               mile: 8,
    00 3c               limit: 60,
                    }

### `0x81`: IAmDispatcher (Client->Server)

Fields:

- `numroads: u8`
- `roads: [u16]` (array of `numroads` u16 values)

Identifies this client as a dispatcher responsible for the listed roads.

It is an error for a client that has already identified itself to send this message.

    Hexadecimal:    Decoded:
    81              IAmDispatcher{
    03                  roads: [
    00 42                   66,
    01 70                   368,
    13 88                   5000
                        ]
                    }

## Example Session

Three clients connect. Clients 1 & 2 are cameras on road 123 with a 60 mph limit. Client 3 is a dispatcher for road 123. Car "UN1X" passes camera 1 at t=0 and camera 2 at t=45: 1 mile in 45 seconds = 80 mph, exceeding the 60 mph limit. A ticket is dispatched.

### Client 1: camera at mile 8

    <-- IAmCamera{road: 123, mile: 8, limit: 60}
    <-- Plate{plate: "UN1X", timestamp: 0}

### Client 2: camera at mile 9

    <-- IAmCamera{road: 123, mile: 9, limit: 60}
    <-- Plate{plate: "UN1X", timestamp: 45}

### Client 3: dispatcher for road 123

    <-- IAmDispatcher{roads: [123]}
    --> Ticket{plate: "UN1X", road: 123, mile1: 8, timestamp1: 0, mile2: 9, timestamp2: 45, speed: 8000}

## Detailed Rules

### Dispatchers

When the server generates a ticket for a road with multiple dispatchers, it may **choose arbitrarily** but must **never send the same ticket twice**.

If a dispatcher disconnects before receiving a sent ticket, the **ticket is lost**.

If no dispatcher is connected for a road, the server must **queue the ticket** and deliver it when a dispatcher for that road connects.

### Non-adjacent cameras

A car can skip cameras. You must generate a ticket if the average speed exceeded the limit between **any pair** of observations on the same road, not just adjacent cameras.

### One ticket per car per day

The server may send **no more than 1 ticket** for any given car on any given day.

Days are defined by `floor(timestamp / 86400)`.

Where a ticket spans multiple days (timestamp1 and timestamp2 fall on different days), the ticket applies to **every day** from the start to the end, inclusive. A subsequent violation on any of those covered days must **not** generate another ticket.

### Speed threshold

It is **always required** to ticket a car exceeding the limit by 0.5 mph or more. It is **acceptable to omit** tickets for cars exceeding by less than 0.5 mph. It is **never acceptable** to ticket a car at or below the limit.

### Speed overflow

The speed field is `u16`, capping at 655.35 mph. No car will exceed this speed, so overflow is not a concern.
