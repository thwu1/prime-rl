A DERP (Designated Encrypted Relay for Packets) relay server's traffic has been captured at `/app/relay_capture.bin`. The following reference materials are available:

- `/app/envelope_spec.md` — Binary capture envelope format (DPCAP v1)
- `/app/derp_spec.md` — DERP protocol wire format and frame type specifications
- `/app/schema.sql` — Required SQLite database schema for the audit
- `/app/certs/server_identity.pem` — Server's Ed25519 public key certificate
- `/app/acl_policy.json` — Access control policy governing permitted client-to-client communication (first matching rule wins, with a default action)
- `/app/topology.json` — Expected mesh topology (lists authorized mesh peers and expected clients)

Perform a forensic security audit of this relay's captured traffic. Write `/app/audit.py` that parses the binary capture, reconstructs protocol state across all connections, and produces two output artifacts:

**`/app/audit.db`** — A SQLite database conforming to `/app/schema.sql`. All four tables (`frames`, `connections`, `routing_events`, `anomalies`) must be fully populated. You must detect all security anomalies present in the capture. The anomaly types to report are: `split_brain`, `handshake_violation`, `unauthorized_mesh_op`, `acl_violation`, and `phantom_peer`. Correct classification requires understanding the DERP protocol state machine, the mesh peer privilege model, and the access control policy semantics.

**`/app/audit.json`** — A JSON report with the following top-level keys:

- `total_frames` (integer)
- `frame_type_distribution` (object: frame type name → count)
- `connections_summary` (array of objects, each with: `conn_id`, `client_key_hex`, `is_mesh_peer`, `handshake_complete`, `frame_count`)
- `server_key_verified` (boolean)
- `server_key_fingerprint` (string: SHA-256 hex digest of the raw 32-byte server public key as it appears in the capture)
- `routing_summary` (object: `total_send`, `total_recv`, `total_forward`, `total_data_bytes`)
- `anomaly_counts` (object: anomaly type → count)
- `total_anomalies` (integer)
- `acl_compliance` (object: `evaluated_sends`, `permitted_sends`, `denied_sends`, `compliance_ratio`)