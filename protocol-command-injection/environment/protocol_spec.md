# Ground Station Control Protocol (GSCP) - Partial Specification

**Classification: INTERNAL USE ONLY**
**Document Version: 0.3 (DRAFT)**
**Status: Incomplete - reverse-engineered from network captures**

## 1. Overview

The Ground Station Control Protocol (GSCP) is a custom binary protocol used
for communication between ground station operators and the station control
software. This specification was partially reverse-engineered from captured
network traffic and may contain inaccuracies.

The protocol operates over TCP, typically on port 9090.

## 2. Packet Structure

### 2.1 Request Packets

All request packets follow this structure:

| Offset | Size (bytes) | Field          | Description                              |
|--------|-------------|----------------|------------------------------------------|
| 0      | 2           | Magic          | Protocol magic bytes: `0x47 0x53` ("GS") |
| 2      | 1           | Version        | Protocol version                         |
| 3      | 1           | Type           | Packet type identifier                   |
| 4      | 2           | Payload Length | Length of payload data (big-endian)       |
| 6      | variable    | Payload        | Packet payload data                      |

**Note:** Some captures suggest additional trailing bytes after the payload,
but their purpose has not been determined. They may be related to integrity
verification.

### 2.2 Response Packets

Response packets have a similar structure with an additional status field:

| Offset | Size (bytes) | Field          | Description                              |
|--------|-------------|----------------|------------------------------------------|
| 0      | 2           | Magic          | `0x47 0x53`                              |
| 2      | 1           | Version        | Protocol version                         |
| 3      | 1           | Type           | Same type as the request                 |
| 4      | 1           | Status         | `0x00` = Success, `0x01` = Error         |
| 5      | 2           | Payload Length | Big-endian                               |
| 7      | variable    | Payload        | Response data or error message           |

**Note:** Responses may also include trailing integrity bytes similar to
requests.

### 2.3 Protocol Version

The current protocol version observed in captures is `0x01`. However, some
newer captures show version `0x02`. The server may reject connections with
incorrect version numbers.

## 3. Packet Types

| Value | Name   | Auth Required | Description              |
|-------|--------|---------------|--------------------------|
| 0x01  | AUTH   | No            | Authentication request   |
| 0x02  | TELEM  | Yes           | Telemetry data query     |
| 0x03  | CMD    | Yes (Admin)   | Station command dispatch |
| 0x04  | STATUS | No            | System status query      |
| 0x05  | PING   | No            | Connection keepalive     |

## 4. Authentication (Type 0x01)

The AUTH packet payload contains user credentials. The format appears to use
a delimiter between username and password, though the exact delimiter has
varied in captures (semicolon, comma, or other characters have been observed
in different sessions).

**Known access levels:**
- `OPERATOR` - Can query telemetry and status
- `ADMIN` - Full access including station commands

Upon successful authentication, the server responds with a message indicating
the granted access level. Authentication is per-session; once authenticated,
subsequent requests on the same TCP connection use the authenticated identity.

## 5. Telemetry Query (Type 0x02)

Queries telemetry data from station subsystems. The payload should contain the
subsystem identifier as an ASCII string. The server passes the subsystem name
to an internal query mechanism and returns the results.

**Observed subsystem identifiers (partial list):**
- `power` - Power subsystem metrics
- `thermal` - Temperature monitoring data

Other subsystems likely exist but have not been enumerated from captures.

Requires at least OPERATOR-level authentication.

## 6. Station Command (Type 0x03)

Executes station management commands. Requires ADMIN-level authentication.
Known commands have not been fully enumerated from captures.

## 7. Status (Type 0x04)

Returns general station status information. No payload required.
No authentication required.

## 8. Security Notes

- Default or hardcoded credentials may exist for initial deployment but have
  not been confirmed in captures
- The protocol does not appear to use encryption
- Input validation rigor appears to vary across different packet handlers -
  some handlers may be more permissive than others regarding payload content
- Access control enforcement is checked per-request based on session state
- The internal query mechanism used by the TELEM handler has not been fully
  characterized
