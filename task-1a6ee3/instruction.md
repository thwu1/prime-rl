Build a p0f-style passive TCP/IP fingerprinting tool that identifies the source operating system from raw TCP SYN packets.

A PCAP file at `/app/captures/syn_packets.pcap` contains TCP packets (including non-SYN packets that must be filtered out). A p0f-format fingerprint database is at `/app/signatures/tcp_syn.fp` — study it to understand the signature format, wildcard matching rules, and quirk definitions.

Create `/app/fingerprint.py` that parses the PCAP from raw bytes (no packet-parsing libraries like scapy/dpkt), extracts TCP SYN signatures, matches them against the database, and writes `/app/results.json`.

The signature format is `ver:ittl:olen:mss:wsize,scale:olayout:quirks:pclass`. Your implementation must correctly handle:

- **Initial TTL guessing**: round the observed TTL up to the nearest value in {32, 64, 128, 255}
- **Window size classification**: use `mss*N` if window is an exact multiple of MSS, `mtu*N` if an exact multiple of (MSS+40), otherwise the absolute value
- **TCP option parsing**: MSS (kind 2), Window Scale (kind 3), SACK Permitted (kind 4), Timestamps (kind 8), NOP (kind 1), EOL (kind 0) — for EOL, count remaining padding bytes as `eol+N`
- **Quirk detection**: `df` (DF flag), `id+` (non-zero IP ID with DF set), `id-` (zero IP ID without DF), `ecn` (IP ToS ECN bits set), `ack+`/`ack-`, `uptr+`/`urgf`, `pushf`, `ts1-`/`ts2+`, `opt+` (non-zero EOL padding), `exws` (wscale>14), `seq-` (zero seq), `0+` (MBZ bit)
- **Database matching**: `*` in database fields matches any value; match on all 8 colon-separated fields

Output `/app/results.json` as a JSON array. Each SYN packet (SYN set, ACK not set) produces one object with: `packet_index` (0-based position in the PCAP), `src_ip`, `dst_ip`, `src_port`, `dst_port`, `signature` (the extracted p0f signature string with actual values), `os_class`, `os_name` (from the matched database label, or `"unknown"` if no match).