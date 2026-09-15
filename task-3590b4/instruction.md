A two-node DERP relay mesh is under security audit. Binary protocol captures from both relay nodes, a WireGuard peer configuration, and an authorization policy are provided. Analyze the captures and produce a forensic audit report at `/app/audit_report.json`.

The report must contain:

**Per-node analysis** (`node1`, `node2` keys): `total_frames`, `session_count` (determined from the protocol's connection handshake structure), `frame_type_counts` (map of frame type name to count, using names from the protocol specification), and `data_bytes` with `send`, `recv`, `forward` sub-fields — the byte counts of actual packet data relayed via the corresponding frame types, as defined by each frame type's layout in the protocol specification.

**`peer_key_mapping`**: Map each DERP peer key observed in captures (lowercase hex) to its peer name from the WireGuard configuration. Only include peers that have a matching config entry.

**`unauthorized_peers`**: Peers observed in captures with no corresponding entry in the WireGuard configuration. Each entry: `key` (hex), `node`, `session_index` (0-based).

**`privilege_violations`**: Peers that sent frame types not permitted by their assigned role in the authorization policy. Each entry: `peer_name`, `peer_key` (hex), `node`, `frame_type`, `peer_role`, `required_role` (the least privileged role that permits the frame type).

**`node_policy_violations`**: Peers connecting to relay nodes outside their `allowed_nodes`. Each entry: `peer_name`, `peer_key` (hex), `node`, `allowed_nodes`.

**`protocol_violations`**: Frames violating the protocol's handshake ordering requirements as described in the protocol specification. Each entry: `node`, `session_index`, `violation` (description containing the offending frame type name), `frame_index_in_session` (0-based within the session).

**`cross_node_forward_packets`**: Total ForwardPacket count across both nodes.
**`cross_node_forward_bytes`**: Total ForwardPacket data bytes across both nodes.
**`total_data_bytes`**: Sum of all send + recv + forward data bytes across both nodes.

**`mesh_topology`**: `node1_peer_count` and `node2_peer_count` (total unique peers identified per node, including unauthorized), `shared_peers` (sorted list of peer names appearing on both nodes; unnamed/unauthorized peers excluded).

Data sources:
- `/app/node1_capture.bin` and `/app/node2_capture.bin`
- `/app/wg_peers.conf` — WireGuard configuration with peer identities
- `/app/peer_policy.json` — authorization policy with roles and allowed nodes
- `/app/derp_protocol_spec.txt` — DERP wire protocol specification