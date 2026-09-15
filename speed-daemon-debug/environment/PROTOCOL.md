# LRCP — Line Reversal Control Protocol

## Overview

LRCP is a connection-oriented byte-stream protocol that runs on top of UDP.
It turns unreliable, out-of-order UDP packets into a pair of **reliable,
in-order byte streams** — one in each direction.

To achieve this it maintains a per-session **payload length counter on each
side**, labels every payload transmission with its **position in the overall
stream**, and retransmits data that has been dropped.  A sender detects a
drop either by not receiving an acknowledgement within an expected time
window, or by receiving a duplicate of a prior acknowledgement.

Client sessions are identified by a numeric *session* token supplied by the
client.  You may assume that **session tokens uniquely identify clients** and
that the peer for any given session is at a fixed IP address and port number.

---

## Messages

Messages are sent in **UDP packets**.  Each UDP packet contains a single LRCP
message.  A message is a series of **values separated by forward-slash**
characters (`/`), and starts and ends with a forward slash:

    /data/1234567/0/hello/

The first field is a string specifying the message type (here, `data`).
The remaining fields depend on the message type.  Numeric fields are
represented as ASCII decimal text.

### Validation

Illegal packets must be **silently ignored**.

1. Contents must begin with `/`, end with `/`, contain a valid message type,
   and have the correct number of fields for that type.
2. Numeric field values must be **less than 2147483648** (i.e. fit in a
   signed 32-bit integer).
3. LRCP messages must be **smaller than 1000 bytes**.  Data may need to be
   split across multiple `data` messages to stay below this limit.

### Parameters

| Parameter | Suggested default |
|---|---|
| **Retransmission timeout** — wait before resending unacknowledged data | 3 seconds |
| **Session expiry timeout** — wait before treating a silent peer as gone | 60 seconds |

---

### 1. `/connect/SESSION/`

Sent by the client to the server to open a session.  `SESSION` is a
non-negative integer.

If no response arrives within the retransmission timeout the client will
re-send the `connect`, possibly multiple times.

#### When you receive a `connect`

1. If no session with this token exists, open one and associate it with the
   sender's IP address and port.
2. Send `/ack/SESSION/0/` to confirm the session is open (even for
   duplicates — the first `ack` may have been lost).

Example — open session 1234567:

    <-- /connect/1234567/
    --> /ack/1234567/0/

---

### 2. `/data/SESSION/POS/DATA/`

Transmits payload data.  `POS` is a non-negative integer giving the
**position in the stream** where `DATA` belongs.

Where `DATA` contains forward-slash (`/`) or backslash (`\`) characters the
sender must **escape** them by prepending each with a backslash
(`foo/bar\baz` becomes `foo\/bar\\baz`).  The receiver must reverse this
before passing data to the application layer.

`POS` refers to the position of **unescaped application-layer bytes**, not
escaped bytes.

Behaviour is undefined if overlapping data differs from what was already
received.

When sending data, retransmit if unacknowledged within the retransmission
timeout.  If still unacknowledged after the session expiry timeout, close the
session.

#### When you receive a `data`

1. Session not open → send `/close/SESSION/` and stop.
2. Everything up to `POS` already received → unescape `\\` and `\/`, compute
   the total `LENGTH` of in-order data received (including any new bytes from
   this message), send `/ack/SESSION/LENGTH/`, and pass new data to the
   application layer.
3. Gap before `POS` → send a duplicate of the most recent `ack` (or
   `/ack/SESSION/0/`) to provoke retransmission of the missing range.

Examples:

    <-- /data/1234567/0/hello/
    --> /ack/1234567/5/

    <-- /data/1234568/0/\//
    --> /ack/1234568/1/       # 1, not 2: "\/" is one application byte

---

### 3. `/ack/SESSION/LENGTH/`

Acknowledges receipt of payload data.  `LENGTH` is a non-negative integer
telling the sender how many bytes have been successfully received so far.

#### When you receive an `ack`

1. Session not open → send `/close/SESSION/` and stop.
2. `LENGTH` **<= largest** `LENGTH` you have previously received → do nothing
   (delayed duplicate).
3. `LENGTH` **> total payload you have sent** → peer is misbehaving; close
   the session.
4. `LENGTH` **< total payload sent** → retransmit all payload after the first
   `LENGTH` bytes.
5. `LENGTH` **== total payload sent** → nothing to do.

---

### 4. `/close/SESSION/`

Requests session closure; can be sent by either side.

When you receive `/close/SESSION/`, send `/close/SESSION/` back.

    <-- /close/1234567/
    --> /close/1234567/

---

## Example session

    <-- /connect/12345/
    --> /ack/12345/0/
    <-- /data/12345/0/Hello, world!/
    --> /ack/12345/13/
    <-- /close/12345/
    --> /close/12345/

---

## Application layer: Line Reversal

Accept LRCP connections.  Support **at least 20 simultaneous sessions**.

Reverse each line of input and send it back.  Lines are ASCII text delimited
by newline (`\n`) and are no longer than 10 000 characters each.

A single `data` message may carry bytes for multiple lines — chunking is
arbitrary.  A line is not complete until its newline arrives.  The
abstraction presented to the application layer is a pair of **byte streams**.

### Application-layer example

    <-- hello
    --> olleh
    <-- Hello, world!
    --> !dlrow ,olleH

### Same session at the LRCP layer

    <-- /connect/12345/
    --> /ack/12345/0/
    <-- /data/12345/0/hello\n/
    --> /ack/12345/6/
    --> /data/12345/0/olleh\n/
    <-- /ack/12345/6/
    <-- /data/12345/6/Hello, world!\n/
    --> /ack/12345/20/
    --> /data/12345/6/!dlrow ,olleH\n/
    <-- /ack/12345/20/
    <-- /close/12345/
    --> /close/12345/

(`\n` above denotes ASCII newline, 0x0A.)
