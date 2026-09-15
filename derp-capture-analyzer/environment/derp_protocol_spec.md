# DERP Protocol Specification (Simplified)

DERP (Detoured Encrypted Routing Protocol) is a packet relay protocol that routes
packets to clients using curve25519 public keys (32 bytes) as addresses. This
document describes the wire format for a capture analysis tool.

## Capture File Format (DPCAP v1)

Capture files use the `.dpcap` extension and have this structure:

### File Header
- 6 bytes: magic `DPCAP\x01` (ASCII "DPCAP" + version byte 0x01)

### Records
Each record immediately follows the previous:
- 8 bytes: timestamp in **microseconds** since epoch (uint64 big-endian)
- 1 byte: direction (`0x00` = server-to-client, `0x01` = client-to-server)
- Then the raw DERP frame (header + body, see below)

## DERP Frame Format

### Frame Header (5 bytes)
- 1 byte: frame type (see table below)
- 4 bytes: body length in bytes (uint32 big-endian), NOT including this 5-byte header

### Frame Types

| Type Byte | Name            | Body Layout                                                |
|-----------|-----------------|-------------------------------------------------------------|
| `0x01`    | ServerKey       | 8B magic `DERP\xf0\x9f\x94\x91` + 32B server public key   |
| `0x02`    | ClientInfo      | 32B client public key + 24B nonce + remaining encrypted JSON|
| `0x03`    | ServerInfo      | 24B nonce + remaining encrypted JSON                        |
| `0x04`    | SendPacket      | 32B destination public key + remaining packet bytes         |
| `0x05`    | RecvPacket      | 32B source public key + remaining packet bytes (protocol v2)|
| `0x06`    | KeepAlive       | empty (0 bytes)                                             |
| `0x07`    | NotePreferred   | 1B: `0x01` = preferred, `0x00` = not preferred              |
| `0x08`    | PeerGone        | 32B public key + 1B reason code                             |
| `0x09`    | PeerPresent     | 32B public key + optional 16B IP + 2B port (BE) + 1B flags  |
| `0x0a`    | ForwardPacket   | 32B source key + 32B destination key + remaining packet bytes|
| `0x10`    | WatchConns      | empty (0 bytes)                                             |
| `0x11`    | ClosePeer       | 32B public key of peer to close                             |
| `0x12`    | Ping            | 8B payload                                                  |
| `0x13`    | Pong            | 8B payload (echo of Ping)                                   |
| `0x14`    | Health          | UTF-8 text (empty = healthy)                                |
| `0x15`    | Restarting      | 4B reconnect_in_ms (uint32 BE) + 4B try_for_ms (uint32 BE) |

### Protocol Constants
- Magic string in ServerKey frame: `DERP\xf0\x9f\x94\x91` (8 bytes: ASCII "DERP" + UTF-8 for U+1F511)
- KeepAlive interval threshold: 120 seconds (120,000,000 microseconds). If the gap
  between consecutive KeepAlive frames exceeds this, it is a timing anomaly.
- All multi-byte integers are big-endian.
- Public keys are always 32 bytes.
- Nonces are always 24 bytes.

## Protocol State Machine

A valid DERP session handshake must proceed in this exact order:
1. Server sends `ServerKey` (direction=0x00, type=0x01)
2. Client sends `ClientInfo` (direction=0x01, type=0x02)
3. Server sends `ServerInfo` (direction=0x00, type=0x03)

After the handshake, any frame type may appear in steady state. The handshake
is **invalid** if:
- The first frame is not `ServerKey` from the server
- `ClientInfo` appears before `ServerKey`
- `ServerInfo` appears before `ClientInfo`
- Any data frame (SendPacket, RecvPacket, etc.) appears before handshake completion

### Anomaly Detection Rules
1. **Invalid handshake**: handshake steps out of order or missing
2. **Unknown frame type**: any frame type byte not listed in the table above
3. **Bad ServerKey magic**: the first 8 bytes of a ServerKey frame body do not match the expected magic
4. **KeepAlive gap exceeded**: gap between consecutive KeepAlive frames > 120 seconds
5. **Unmatched Ping**: a Ping frame whose 8-byte payload never appears in a subsequent Pong
6. **Duplicate Ping payload**: two or more Ping frames with identical 8-byte payloads
7. **Pre-handshake data**: SendPacket, RecvPacket, or ForwardPacket before handshake completion

## Session Lifecycle Integrity

The `PeerPresent` and `PeerGone` frames define the lifecycle of peer reachability on a relay.
After the session handshake completes:

- `PeerPresent(key=X)` signals that peer X is reachable on this relay
- `PeerGone(key=X)` signals that peer X has departed from this relay

**Ghost traffic** occurs when data frames reference peers in an inconsistent lifecycle state:

- **ghost_recv**: A `RecvPacket` with source key X appears after a `PeerGone(key=X)` without
  an intervening `PeerPresent(key=X)`. This suggests stale routing, packet injection, or relay
  state desynchronization.
- **ghost_send**: A `SendPacket` with destination key X appears after a `PeerGone(key=X)` without
  an intervening `PeerPresent(key=X)`. This suggests the client is sending to a peer it should
  know has departed.

Ghost traffic anomalies should be reported in the `anomalies` list with the format `ghost_recv: <peer_key_hex>`
or `ghost_send: <peer_key_hex>`.

**Important**: Traffic to/from peers that were **never** announced via `PeerPresent` is NOT considered
ghost traffic — only traffic after an explicit `PeerGone` constitutes a lifecycle violation. The
`gone_peers` set should be reset when a new session begins (i.e., on session boundary detection).

## Traffic Flow Correlation (Multi-Relay Mode)

In multi-relay analysis, the tool must detect relay-mediated communication paths by correlating
packet timing across relays. This analysis reveals the actual traffic flow graph through the relay
mesh, which is critical for understanding communication topology and detecting potential traffic
analysis vulnerabilities.

A **traffic correlation** exists when:
1. On relay R1, the session client (peer A) sends to destination D (`SendPacket` with `dest_key=D`)
   at timestamp T1
2. On relay R2, a different session client that matches D receives from source A (`RecvPacket`
   with `src_key=A`) at timestamp T2
3. `|T1 - T2| < 1,000,000` microseconds (1-second correlation window)

Each unique `(src_peer, dst_peer, src_relay, dst_relay)` tuple with at least one timing match
constitutes a correlated flow. The `correlated_packets` count is the number of individual
send-recv timing matches within the correlation window.

## Threat Classification and Risk Scoring (Multi-Relay Mode)

Each peer observed across the relay mesh is assigned a threat assessment consisting of:
1. A **risk_score** (integer, 0–100): weighted sum of detected security signals, capped at 100
2. A **level** (categorical): derived from risk_score thresholds
3. A **signals** list: sorted list of contributing signal type names

### Signal Weights

| Signal                 | Weight | Rationale                                              |
|------------------------|--------|--------------------------------------------------------|
| `blocked_peer`         | 60     | Known-compromised key on blocklist                     |
| `nonce_reuse`          | 40     | NaCl nonce reuse enables plaintext recovery            |
| `unauthorized_relay`   | 20     | Policy violation — peer on wrong relay                 |
| `ghost_traffic`        | 15     | Session lifecycle violation suggests packet injection  |
| `unauthorized_destination` | 15 | Policy violation — sending to forbidden destination    |
| `cross_relay_conflict` | 10     | Simultaneous sessions may indicate credential sharing  |

Each signal type counts **once** per peer regardless of how many times it occurs across relays.
The risk_score is the sum of weights for all present signals, capped at 100.

### Level Thresholds

| Score Range | Level    |
|-------------|----------|
| 0           | none     |
| 1–19        | low      |
| 20–39       | medium   |
| 40–59       | high     |
| ≥ 60        | critical |
