Implement `/app/server.py` — a UDP server on port 9000 implementing the LRCP
reliable transport protocol and line-reversal application defined in
`/app/PROTOCOL.md`.

LRCP provides reliable, in-order byte streams over UDP using session tracking,
positional data labeling, escape-aware framing, acknowledgement-driven flow
control, and timeout-based retransmission — essentially a minimal TCP analogue.
The application layer reverses each newline-delimited ASCII line and sends it
back over the same LRCP session.

The server must handle 20+ concurrent sessions, retransmit unacknowledged data
(3 s default), respect the <1000 byte per-message limit with correct data
chunking, correctly escape and unescape `/` and `\` in data fields (with
position counters tracking *unescaped* bytes), and expire sessions after 60 s
of inactivity.

Start: `python3 /app/server.py` — binds `0.0.0.0:9000/udp`.