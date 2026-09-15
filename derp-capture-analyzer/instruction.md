A DERP (Detoured Encrypted Routing Protocol) mesh relay infrastructure has captured traffic across multiple relay nodes. Build an executable forensic analysis tool at `/app/mesh_forensics` that performs comprehensive protocol and security analysis, outputting valid JSON to stdout conforming to `/app/output_schema.json`.

The tool must support three modes:

**Single-file mode** (`/app/mesh_forensics <file.dpcap>`): Full protocol forensics on a DPCAP binary capture per `/app/derp_protocol_spec.md`. Beyond frame parsing and handshake validation, the tool must detect multi-session captures (handshake state machine resets), perform session lifecycle integrity analysis — identifying ghost traffic where data frames reference peers after their PeerGone was announced without a subsequent PeerPresent — and correlate ping/pong liveness probes.

**pcap mode** (`/app/mesh_forensics --pcap <file.pcap>`): Extract DERP frames from standard pcap captures using tshark and analyze the frame stream.

**Multi-relay mode** (`/app/mesh_forensics --dir <directory> [--db <path.db>]`): Comprehensive cross-relay security assessment. Must reconstruct mesh topology, detect cryptographic nonce reuse across sessions (indicating NaCl confidentiality compromise), identify bridge peers spanning relay segments, detect temporal session conflicts, perform traffic flow correlation analysis to reveal relay-mediated communication paths (cross-relay packet timing within a 1-second window), and classify per-peer threat levels using weighted risk scoring that synthesizes all security signals into both a numeric risk_score and categorical level. When `--db` is provided, enforce peer access policies from the SQLite database (schema matches `/app/relay_metadata.db`) and incorporate violations into threat assessment.

## Reference materials

- `/app/derp_protocol_spec.md` — DPCAP file format, DERP wire format, frame types, protocol state machine, anomaly detection rules, session lifecycle semantics, traffic correlation semantics, and threat scoring model
- `/app/relay_metadata.db` — SQLite database with relay node metadata and peer access policies
- `/app/output_schema.json` — Complete JSON output schema for all three modes