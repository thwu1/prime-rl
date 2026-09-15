Analyze 12 IPv6 packets with SRv6 Segment Routing Headers in `/app/captures/traffic.pcap` against the topology and policy specification in `/app/topology.json`.

The pcap uses LINKTYPE_RAW (DLT 101) — no link-layer framing; packets begin directly with IPv6 headers. All IPv6 addresses in output must use RFC 5952 compressed notation.

## Output

Write two files:

**`/app/output/analysis.json`** — a JSON array with one object per packet:
- `packet_index` (int): 0-based capture order
- `is_valid` (bool): true iff all RFC 8754 and topology checks pass
- `errors` (string[]): alphabetically sorted error type keys from `topology.error_types`
- `matched_path` (string|null): matching `valid_paths` name, or null
- `srh_digest` (string): first 16 hex characters of SHA-256 of the raw SRH extension bytes — `(Hdr Ext Len + 1) × 8` bytes starting at byte offset 40 of each raw packet

**`/app/output/summary.json`** — aggregate metrics:
- `total_packets` (int)
- `valid_count` (int)
- `invalid_count` (int)
- `violation_score` (int): sum of `topology.violation_weights[error]` for every error across all packets
- `unique_paths_seen` (string[]): alphabetically sorted list of all distinct non-null `matched_path` values

## SRH semantics

Per RFC 8754, the SRH stores segment addresses in reverse order. To reconstruct the forward-order segment list, reverse the SRH addresses array. Match forward-order lists against `valid_paths` even for error packets — report a match whenever the underlying segment addresses correspond to a valid path regardless of other SRH field errors.

The `invalid_path` error applies only when all RFC-level structural checks pass but no valid path matches the segment sequence.

```
```