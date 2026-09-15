`/app/tcp_tracker.py` is a TCP connection state tracker built with scapy. It reads pcap files from `/app/captures/`, follows each connection's TCP state machine, and writes a JSON trace to `/app/trace.json` containing state transitions, byte counts, retransmission counts, and window information per connection. The output schema and field semantics are documented in the tracker source.

The tracker produces incorrect results for several protocol edge cases exercised by the captures in `/app/captures/`. Both `tshark` and `scapy` are available.

**Evaluate and Repair**: Use `tshark` to independently analyze each capture and extract ground-truth TCP payload byte counts per direction. Compare these against the tracker's current output to identify all discrepancies. Fix every defect in `/app/tcp_tracker.py` so it produces correct output for all captures.

**Design and Extend**: The tracker's retransmission detection conflates out-of-order segment arrivals with true retransmissions—any segment with a sequence number below the high-water mark is counted as a retransmit, even if its data was never received. Extend the tracker with received-range tracking to correctly distinguish the two cases, and add a `reorder_events` integer field to the per-connection JSON output. Generate `/app/captures/reorder.pcap` using scapy: a single TCP connection where the client sends 4 × 256-byte data segments with segment 3 arriving before segment 2, followed by a genuine retransmission of segment 1, plus 128 bytes from the server, ending with a normal 4-way close. Ensure the tracker handles this capture correctly.

**Cross-Validate**: Write `/app/cross_validation.json` comparing the tracker's per-connection byte counts against tshark-derived unique payload byte totals for every capture including `reorder.pcap`. All entries must have `match: true`. Schema:

```json
{"captures": [{"file": "...", "tracker_client_bytes": 0, "tracker_server_bytes": 0, "tshark_client_bytes": 0, "tshark_server_bytes": 0, "match": true}]}
```

Run: `python3 /app/tcp_tracker.py /app/captures/`