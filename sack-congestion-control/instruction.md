A UDP-based reliable file transfer protocol is implemented in `/app/`. It currently uses Go-Back-N (GBN) ARQ: on any timeout the sender retransmits every unacknowledged packet, and the receiver sends only cumulative ACKs with no information about out-of-order data.

The environment consists of five files:

- `/app/packet.py` — packet serialization/deserialization with Internet checksum, SACK block fields in the header (already defined but unused).
- `/app/emulator.py` — UDP link emulator introducing configurable loss, delay, reordering, and corruption.
- `/app/sender.py` — GBN sender (needs upgrade).
- `/app/receiver.py` — GBN receiver (needs upgrade).
- `/app/run_transfer.py` — orchestrator that wires sender, emulators, and receiver together for a file transfer and verifies MD5 integrity.

Modify `/app/sender.py` and `/app/receiver.py` so the protocol meets these requirements:

1. **SACK generation** — the receiver must include up to 3 Selective Acknowledgment blocks in every ACK, each block a `(left_edge, right_edge)` byte range representing a contiguous run of out-of-order data buffered by the receiver.

2. **Selective retransmission** — the sender must process received SACK blocks to identify which specific packets the receiver already holds and retransmit only truly missing data, not the entire window.

3. **TCP Reno congestion control** — the sender must maintain a floating-point congestion window (`cwnd`, starting at 1 packet) and slow-start threshold (`ssthresh`, starting at 64):
   - *Slow start*: `cwnd += 1` per new cumulative ACK; transition to congestion avoidance when `cwnd >= ssthresh`.
   - *Congestion avoidance*: `cwnd += 1/cwnd` per new cumulative ACK.
   - *Fast retransmit / fast recovery*: on 3 duplicate ACKs, set `ssthresh = cwnd/2`, `cwnd = ssthresh + 3`, retransmit the first unacked non-SACKed packet, and inflate `cwnd` by 1 for each subsequent duplicate ACK; on a new cumulative ACK, deflate `cwnd = ssthresh` and enter congestion avoidance.
   - *Timeout*: set `ssthresh = cwnd/2`, `cwnd = 1`, return to slow start.
   - The effective send window is `min(cwnd, WINDOW_SIZE)` packets, counting only non-SACKed packets in flight.

4. **Logging** — the sender must log events so that automated tests can verify behavior:
   - Each new cumulative ACK: event `ACK` with keys `ack_num`, `cwnd`, `ssthresh`, `state`, `sack_blocks`.
   - Each fast retransmit: event `FAST_RETRANSMIT` with `seq`, `cwnd`, `ssthresh`.
   - Each timeout: event `TIMEOUT` with `seq`, `cwnd`, `ssthresh`.

The modified protocol must transfer files correctly (MD5 match) under 0–20 % packet loss with reordering and corruption, within the time limits enforced by the test suite.