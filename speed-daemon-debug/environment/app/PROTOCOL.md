# Speed Daemon Binary Protocol Specification

## Overview

A server that coordinates enforcement of average speed limits on a road network.
The server handles two types of TCP client: **cameras** and **ticket dispatchers**.

Cameras observe number plates at known positions on roads and report them to the
server. When the server determines that a car exceeded the speed limit between
two observations on the same road, it generates a ticket and sends it to an
appropriate dispatcher.

## Data Types

### `u8`, `u16`, `u32`

Unsigned integers of 8, 16, and 32 bits respectively, transmitted in network
byte order (big endian).

### `str`

A length-prefixed string: a single **`u8`** containing the string length
(0--255), followed by that many bytes of ASCII character data.

## Message Types

Each message begins with a single `u8` indicating its type. Messages are
concatenated with no padding or delimiters.

It is an error for a client to send a message type not listed as
**Client -> Server** below.

---

### `0x10`: Error (Server -> Client)

| Field | Type |
|-------|------|
| msg   | str  |

Sent when the client commits a protocol error. The server must disconnect the
client immediately after sending this message.

---

### `0x20`: Plate (Client -> Server)

| Field     | Type |
|-----------|------|
| plate     | str  |
| timestamp | u32  |

Reports an observation of a number plate at the camera's position at the given
timestamp. Cameras may report observations in any order and with any delay.

It is an error for a non-camera client to send a `Plate` message.

---

### `0x21`: Ticket (Server -> Client)

| Field      | Type | Notes                |
|------------|------|----------------------|
| plate      | str  |                      |
| road       | u16  |                      |
| mile1      | u16  |                      |
| timestamp1 | u32  |                      |
| mile2      | u16  |                      |
| timestamp2 | u32  |                      |
| speed      | u16  | 100x miles per hour  |

Generated when a car's average speed between two observations exceeds the road's
speed limit.

**`mile1` and `timestamp1` must refer to the earlier observation (the one with
the smaller timestamp).** `mile2` and `timestamp2` refer to the later one.

The `speed` field is the average speed multiplied by 100, expressed as an
integer.

---

### `0x40`: WantHeartbeat (Client -> Server)

| Field    | Type | Notes        |
|----------|------|--------------|
| interval | u32  | deciseconds  |

Requests periodic heartbeat messages. The **interval is specified in
deciseconds** (tenths of a second). An interval of 10 means a heartbeat every
1.0 second. An interval of 25 means every 2.5 seconds.

An interval of 0 means the client does not want heartbeats (this is the
default).

**It is an error for a client to send multiple `WantHeartbeat` messages on a
single connection**, regardless of the interval values.

---

### `0x41`: Heartbeat (Server -> Client)

No fields. Sent at the interval requested by the client.

---

### `0x80`: IAmCamera (Client -> Server)

| Field | Type | Notes          |
|-------|------|----------------|
| road  | u16  |                |
| mile  | u16  |                |
| limit | u16  | miles per hour |

Identifies this client as a camera at the given position on the given road, with
the given speed limit.

It is an error for a client that has already identified itself to send this
message.

---

### `0x81`: IAmDispatcher (Client -> Server)

| Field    | Type   | Notes          |
|----------|--------|----------------|
| numroads | u8     |                |
| roads    | [u16]  | numroads items |

Identifies this client as a ticket dispatcher responsible for the listed roads.

It is an error for a client that has already identified itself to send this
message.

---

## Behaviour Rules

### Speed Detection

The server must generate a ticket whenever the average speed between **any pair
of observations** of the same car on the same road exceeds the speed limit. Speed
is calculated as `distance / time` in miles per hour.

It is always required to ticket a car exceeding the limit by 0.5 mph or more.
It is acceptable to omit a ticket when the excess is less than 0.5 mph. It is
never acceptable to ticket a car below the speed limit.

### Dispatchers and Ticket Delivery

When the server generates a ticket for a road with connected dispatchers, it
sends the ticket to any one of them.

**If the server generates a ticket for a road that has no connected dispatcher,
it must store the ticket and deliver it once a dispatcher for that road becomes
available.**

If a dispatcher disconnects before receiving a ticket in transit, the ticket is
lost.

### Ticket Day Limits

The server may issue **no more than one ticket** per car per day.

Days are defined as `floor(timestamp / 86400)`.

**Where a ticket spans multiple days, it is considered to apply to every day from
the start day to the end day, inclusive.** A subsequent violation on any of those
days must not produce an additional ticket for that car.

### Heartbeats

The heartbeat interval is in **deciseconds** (1/10 second). The server must
convert this value appropriately when scheduling heartbeat delivery.

Sending multiple `WantHeartbeat` messages on the same connection is an error,
**even if the first request specified an interval of 0**.
