# Speed Daemon Protocol Specification

## Overview

You need to build a TCP server to coordinate enforcement of **average speed limits** on a road network.

Your server handles two types of client: *cameras* and *ticket dispatchers*. Clients connect over TCP and speak a protocol using a **binary format**. You must support at least 150 simultaneous clients.

### Cameras

Each *camera* is on a specific road, at a specific location (mile marker), and has a specific speed limit. Each camera provides this information when it connects to the server. Cameras report each number plate that they observe, along with the timestamp of the observation. Timestamps are unsigned 32-bit Unix timestamps (seconds since 1970-01-01). Cameras can send observations in any order and after any delay, so later messages may have earlier timestamps.

### Ticket dispatchers

Each *ticket dispatcher* is responsible for some number of roads. When the server detects that a car's average speed exceeded the limit between two observations on the same road, it sends a ticket to a dispatcher responsible for that road.

### Roads

Each road is identified by a `u16` number (0–65535). A single road has the same speed limit everywhere. Positions are miles from the start of the road (exact integers).

### Cars

Each car has an uppercase alphanumeric number plate string.

---

## Data types

### `u8`, `u16`, `u32`

Unsigned integers of 8, 16, or 32 bits respectively, transmitted in **big-endian** (network byte order).

    Type | Hex data    | Value
    -------------------------------
    u8   |          20 |         32
    u16  |       00 20 |         32
    u16  |       12 45 |       4677
    u32  | 00 00 00 20 |         32
    u32  | a6 a9 b5 67 | 2796139879

### `str`

A **length-prefixed** string: a single `u8` containing the length (0–255), followed by that many ASCII bytes.

    Type | Hex data                   | Value
    ----------------------------------------------
    str  | 00                         | ""
    str  | 03 66 6f 6f                | "foo"
    str  | 08 45 6C 62 65 72 65 74 68 | "Elbereth"

---

## Message types

Each message starts with a single `u8` specifying the message type, followed by the message content. **Field names are not transmitted** — fields are identified by position. Messages are **concatenated with no padding or delimiter**.

It is an error for a client to send any message type not listed below as "Client→Server".

### `0x10`: Error (Server→Client)

Fields:
 - `msg: str`

When the client does something the protocol declares an error, the server must send an Error message and **immediately disconnect** that client.

    Hex:                            Decoded:
    10 03 62 61 64                  Error{msg: "bad"}
    10 0b 69 6c 6c 65 67 61 6c     Error{msg: "illegal msg"}
    20 6d 73 67

### `0x20`: Plate (Client→Server)

Fields:
 - `plate: str`
 - `timestamp: u32`

This camera has observed the given number plate at its location at the given timestamp. It is an error for a client that has **not** identified itself as a camera to send a Plate message.

    Hex:                    Decoded:
    20 04 55 4e 31 58       Plate{plate: "UN1X",
    00 00 03 e8              timestamp: 1000}

### `0x21`: Ticket (Server→Client)

Fields:
 - `plate: str`
 - `road: u16`
 - `mile1: u16`
 - `timestamp1: u32`
 - `mile2: u16`
 - `timestamp2: u32`
 - `speed: u16` (100× miles per hour)

When the server detects a speed violation between two observations, it generates a Ticket. `mile1`/`timestamp1` must refer to the **earlier** observation (smaller timestamp); `mile2`/`timestamp2` to the later. The `speed` field is the average speed multiplied by 100, as an integer.

    Hex:                        Decoded:
    21 04 55 4e 31 58           Ticket{plate: "UN1X",
    00 42 00 64                  road: 66, mile1: 100,
    00 01 e2 40                  timestamp1: 123456,
    00 6e 00 01 e3 a8            mile2: 110, timestamp2: 123816,
    27 10                        speed: 10000}

### `0x40`: WantHeartbeat (Client→Server)

Fields:
 - `interval: u32` (deciseconds — 10 per second)

Request periodic heartbeats. An interval of 25 means one heartbeat every 2.5 seconds. An interval of 0 means no heartbeats (the default). It is an error for a client to send multiple WantHeartbeat messages on a single connection.

    Hex:            Decoded:
    40 00 00 00 0a  WantHeartbeat{interval: 10}

### `0x41`: Heartbeat (Server→Client)

No fields. Sent at the interval requested by the client.

    Hex:    Decoded:
    41      Heartbeat{}

### `0x80`: IAmCamera (Client→Server)

Fields:
 - `road: u16`
 - `mile: u16`
 - `limit: u16` (miles per hour)

Declares this client as a camera. It is an error for a client that has already identified itself (as either camera or dispatcher) to send an IAmCamera message.

    Hex:                Decoded:
    80 00 7b 00 08      IAmCamera{road: 123, mile: 8,
    00 3c                limit: 60}

### `0x81`: IAmDispatcher (Client→Server)

Fields:
 - `numroads: u8`
 - `roads: [u16]` (array of `u16`, length given by `numroads`)

Declares this client as a ticket dispatcher responsible for the listed roads. It is an error for a client that has already identified itself to send an IAmDispatcher message.

    Hex:                Decoded:
    81 03 00 42         IAmDispatcher{roads: [66,
    01 70 13 88          368, 5000]}

---

## Example session

Three clients connect. Clients 1 & 2 are cameras on road 123 (60 mph limit). Client 3 is a dispatcher for road 123. Car `UN1X` passes camera 1 at mile 8 (timestamp 0) and camera 2 at mile 9 (timestamp 45). Average speed: 1 mile / 45 seconds = 80 mph. Exceeds limit → ticket dispatched.

**Client 1** (camera at mile 8):

    <-- IAmCamera{road: 123, mile: 8, limit: 60}
    <-- Plate{plate: "UN1X", timestamp: 0}

**Client 2** (camera at mile 9):

    <-- IAmCamera{road: 123, mile: 9, limit: 60}
    <-- Plate{plate: "UN1X", timestamp: 45}

**Client 3** (dispatcher):

    <-- IAmDispatcher{roads: [123]}
    --> Ticket{plate: "UN1X", road: 123, mile1: 8, timestamp1: 0,
              mile2: 9, timestamp2: 45, speed: 8000}

---

## Behavioral Rules

### Violation Detection

When the server has two observations of the same car on the same road and the car's average speed between those points exceeded the road's speed limit, a ticket must be generated. Average speed is `distance / time * 3600` (miles divided by seconds, converted to mph).

The server must check **all pairs** of observations on each road, not just consecutive cameras — cars may skip cameras due to obstructed plates or camera failures.

A ticket is **mandatory** when the computed speed exceeds the limit by ≥ 0.5 mph. A ticket must **never** be issued for a car at or below the speed limit.

In the Ticket message, `mile1`/`timestamp1` must refer to the **earlier** observation (smaller timestamp), and `mile2`/`timestamp2` to the **later** observation, regardless of mile order. A car may travel in either direction.

### Ticket Deduplication

The server may send **no more than 1 ticket** for any given car on any given day, across the entire road network. This is a global constraint — a car ticketed on one road may not receive another ticket on any other road on the same day.

Days are defined by `floor(timestamp / 86400)`. Where a ticket's two observations fall on different days, the ticket covers **every day** from `floor(timestamp1 / 86400)` through `floor(timestamp2 / 86400)`, inclusive. Subsequent violations for the same car on any covered day must be suppressed.

### Dispatcher Management

When the server generates a ticket for a road served by multiple connected dispatchers, it may choose any one, but must **never send the same ticket twice**.

If a dispatcher disconnects before receiving a sent ticket, the ticket is lost — this is acceptable.

If no dispatcher for a road is connected when a ticket is generated, the server must **buffer** the ticket and deliver it when a dispatcher for that road subsequently connects.

The server must maintain accurate dispatcher availability throughout connection lifecycles. When a dispatcher disconnects, its writer must be removed from the active registry. Failure to clean up disconnected dispatchers causes tickets to be sent to stale connections and silently lost, rather than being correctly buffered for a future dispatcher.

### Overflow

Nobody on Freedom Island drives faster than 655 mph, so `u16` overflow of the speed field is not a concern.
