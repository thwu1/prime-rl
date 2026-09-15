# DERP Protocol Wire Format

## Overview

DERP (Designated Encrypted Relay for Packets) is a packet relay protocol that
routes packets to clients using curve25519 public keys as addresses. DERP is
used to proxy encrypted WireGuard packets when a direct peer-to-peer path
cannot be established due to NATs, firewalls, or other network obstacles.

## Constants

| Name           | Value                                              |
|----------------|----------------------------------------------------|
| Magic          | `DERP🔑` = bytes `44 45 52 50 f0 9f 94 91` (8B)   |
| FrameHeaderLen | 5 bytes (1 byte type + 4 byte length)              |
| KeyLen         | 32 bytes                                           |
| NonceLen       | 24 bytes                                           |
| ProtocolVersion| 2                                                  |

## Frame Format

Every DERP frame on the wire consists of:

```
+----------+-------------------+------------------+
| Type (1B)| Length (4B BE u32)| Payload (N bytes)|
+----------+-------------------+------------------+
```

- **Type**: single byte identifying the frame type (see below)
- **Length**: big-endian uint32 giving the number of payload bytes that follow
  (does NOT include the 5-byte header itself)
- **Payload**: `Length` bytes of frame-type-specific data

## Frame Types

### FrameServerKey (0x01)
Direction: Server → Client  
Sent upon initial connection as the first frame.

Payload:
- 8 bytes: magic (`DERP🔑`)
- 32 bytes: server's public key
- 0 or more bytes: reserved for future use

### FrameClientInfo (0x02)
Direction: Client → Server  
Sent after receiving FrameServerKey.

Payload:
- 32 bytes: client's public key
- 24 bytes: NaCl nonce
- N bytes: NaCl box encrypted JSON containing ClientInfo

### FrameServerInfo (0x03)
Direction: Server → Client  
Sent after receiving FrameClientInfo to complete the handshake.

Payload:
- 24 bytes: NaCl nonce
- N bytes: NaCl box encrypted JSON containing ServerInfo

### FrameSendPacket (0x04)
Direction: Client → Server  
Client sends a data packet destined for another client.

Payload:
- 32 bytes: destination client's public key
- N bytes: packet data (the actual payload to relay)

### FrameRecvPacket (0x05)
Direction: Server → Client  
Server delivers a data packet from another client (protocol version 2).

Payload:
- 32 bytes: source client's public key (identifies the sender)
- N bytes: packet data

### FrameKeepAlive (0x06)
Direction: Server → Client  
No-op frame to keep the connection alive. No payload (length = 0).

### FrameNotePreferred (0x07)
Direction: Client → Server  
Client tells the server whether this is its preferred/home DERP node.

Payload:
- 1 byte: `0x01` = preferred (home node), `0x00` = not preferred

### FramePeerGone (0x08)
Direction: Server → Client  
Indicates that a previously-connected peer has disconnected.

Payload:
- 32 bytes: public key of the disconnected peer
- 1 byte: reason code
  - `0x00` = peer disconnected from this server
  - `0x01` = server does not know this peer

### FramePeerPresent (0x09)
Direction: Server → Client (mesh peers only)  
Indicates that a peer is connected to this server.

Payload:
- 32 bytes: public key of the connected peer
- (optional) 16 bytes: IP address + 2 bytes: port (big-endian uint16)
- (optional) 1 byte: PeerPresentFlags bitmask

### FrameForwardPacket (0x0a)
Direction: Client → Server (mesh peers only)  
Forwards a packet between meshed DERP nodes in the same region.

Payload:
- 32 bytes: source client's public key
- 32 bytes: destination client's public key
- N bytes: packet data

### FrameWatchConns (0x10)
Direction: Client → Server (mesh peers only)  
Subscribes to peer connection/disconnection events. No payload (length = 0).
Requires mesh key privileges.

### FrameClosePeer (0x11)
Direction: Client → Server (mesh peers only)  
Requests the server to forcefully close a specific peer's connection.
Used for cluster load balancing.

Payload:
- 32 bytes: public key of the peer to disconnect

### FramePing (0x12)
Direction: Either  
Requests the other side to echo back the payload as a FramePong.

Payload:
- 8 bytes: arbitrary ping data

### FramePong (0x13)
Direction: Either  
Response to a FramePing, echoing back the same payload.

Payload:
- 8 bytes: the ping data being replied to

### FrameHealth (0x14)
Direction: Server → Client  
Informs the client about connection health issues.

Payload:
- N bytes: UTF-8 encoded problem description string
  - Empty string means the connection is healthy again
  - Non-empty string describes the problem (e.g. duplicate connection)

### FrameRestarting (0x15)
Direction: Server → Client  
Server announces it is about to restart.

Payload:
- 4 bytes: reconnect_in (big-endian uint32, milliseconds) — advisory delay
  before the client should attempt reconnection
- 4 bytes: try_for (big-endian uint32, milliseconds) — advisory total duration
  the client should keep retrying

## Protocol Flow

### Login Phase
1. Client establishes TCP connection
2. Server sends **FrameServerKey**
3. Client sends **FrameClientInfo**
4. Server sends **FrameServerInfo**

### Steady State
- Server periodically sends **FrameKeepAlive** (or **FramePing**)
- Client responds to **FramePing** with **FramePong**
- Client sends **FrameSendPacket** to transmit data to another client
- Server sends **FrameRecvPacket** to deliver data to the destination client
- Client may send **FrameNotePreferred** to indicate home node preference

### Mesh Operations (privileged)
- Mesh peer sends **FrameWatchConns** to subscribe to connection events
- Server sends **FramePeerPresent** / **FramePeerGone** for connection changes
- Mesh peer uses **FrameForwardPacket** to relay between nodes
- Mesh peer uses **FrameClosePeer** for load balancing
