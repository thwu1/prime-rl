Reference Session Recordings
============================

These files contain annotated hex dumps captured from a known-good
deployment of the speed enforcement server.  Each line shows the
direction (Client -> Server or Server -> Client), a client identifier,
and the raw bytes exchanged over TCP in hexadecimal.

The binary protocol has no published specification — these recordings
and the server source code are the only documentation available.

Files:
  session_basic_ticket.hex    — Camera identification, plate observation,
                                ticket generation, heartbeat lifecycle
  session_reversed_obs.hex    — Plate observations arriving in reverse
                                chronological order
  session_day_spanning.hex    — Ticket spanning a day boundary with
                                subsequent deduplication behavior

Format:
  [timestamp] <client_id> -> S:   client-to-server message bytes
  [timestamp] S -> <client_id>:   server-to-client message bytes

All values are unsigned, big-endian (network byte order).
Strings are length-prefixed with a single byte.
