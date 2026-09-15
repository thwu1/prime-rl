A QUIC deployment is experiencing connection failures during the handshake phase. Forensic artifacts from a failed connection attempt have been collected at `/app/`:

- `/app/captures/connection.pcap` — packet capture containing QUIC traffic from the connection attempt
- `/app/qlogs/server.qlog` — qlog trace from the server endpoint (JSON)
- `/app/qlogs/client.qlog` — qlog trace from the client endpoint (JSON)
- `/app/params/server_tp.hex` — server's raw transport parameters (hex-encoded binary blob as transmitted on the wire)
- `/app/params/client_tp.hex` — client's raw transport parameters (hex-encoded binary blob as transmitted on the wire)
- `/app/certs/cert.pem` — server's TLS certificate

Investigate the connection failure across all artifact sources and produce a comprehensive forensic report at `/app/report.json` containing:

- **`pcap_summary`**: `total_packets` (integer), `client_ip` (string), `server_ip` (string), `server_port` (integer), `quic_versions` (integer array of distinct QUIC version numbers observed in packet headers), `packet_types` (string array of distinct QUIC Long Header packet type names present).

- **`certificate`**: `subject_cn`, `issuer_cn`, `key_type` (e.g. `"EC"`), `serial_hex` (lowercase hex string), `san_dns` (string array of DNS Subject Alternative Names), `is_self_signed` (boolean).

- **`transport_params`**: `server` and `client` sub-objects mapping RFC 9000 transport parameter names (snake_case) to decoded values. Connection IDs and tokens as lowercase hex strings, zero-length parameters as `true`, all others as integers.

- **`violations`**: Array of RFC 9000 compliance violations found in either endpoint's transport parameters. Each entry: `{"source", "parameter", "value", "reason"}`.

- **`negotiated`**: Effective connection parameters computed from both endpoints' advertised values: `effective_idle_timeout_ms`, `client_initiated_max_bidi_streams`, `server_initiated_max_bidi_streams`, `client_to_server_max_data`, `server_to_client_max_data`.

- **`qlog_analysis`**: `server_event_count` (integer), `client_event_count` (integer), `handshake_completed` (boolean), `connection_error` (string — the error code from the qlog), `server_min_rtt_ms` (number — server's minimum RTT measurement).