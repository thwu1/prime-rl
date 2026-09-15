Build `/app/profiler.py` — a network forensics tool that profiles remote TCP hosts from a packet capture. The tool must use `tshark` (`/usr/bin/tshark`) for packet filtering and metadata extraction, combined with raw pcap binary analysis for TCP option parsing.

Usage: `python3 /app/profiler.py /app/capture.pcap /app/fingerprints.db /app/report.json`

The capture at `/app/capture.pcap` contains traffic from multiple hosts including some behind NAT. For each unique source IP that sends TCP SYN-only packets (SYN=1, ACK=0), the profiler must produce:

1. **p0f-compatible OS fingerprint** — build a signature from raw TCP/IP header fields (not tshark display-adjusted values such as relative sequence numbers), match it against `/app/fingerprints.db`. See `/app/SPEC.md` for the 8-field signature format, TCP option layout encoding, quirk flag definitions, and database matching rules.

2. **Hop distance** — difference between guessed initial TTL (nearest value in {32, 64, 128, 255} >= observed) and observed TTL.

3. **TCP timestamp clock analysis** — when a host sends 2+ SYN packets carrying TCP timestamps, estimate the timestamp counter frequency (Hz) via linear regression of TSval against pcap capture time, and derive uptime as `first_tsval / frequency`. Report integer values, or `null` when insufficient data or when NAT is detected.

4. **NAT detection** — flag `nat_detected: true` when a single source IP produces multiple distinct p0f signatures, indicating different OS stacks behind a NAT gateway.

**Output**: JSON array sorted by IP (lexicographic string sort). Each element:
- `ip` (string), `os` (string — DB label or `"unknown"`), `signature` (string — most frequent if NAT), `distance` (int), `uptime_seconds` (int or null), `timestamp_frequency_hz` (int or null), `nat_detected` (bool), `syn_count` (int)
- When `nat_detected` is true, also include `signatures` (sorted array of all distinct signatures observed)

Non-SYN packets, SYN-ACK, non-TCP, and non-IPv4 frames must be silently filtered.