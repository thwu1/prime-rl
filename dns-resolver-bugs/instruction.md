An incident response team captured DNS traffic from a compromised workstation. The pcap at `/app/traffic.pcap` contains a mix of legitimate DNS queries and DNS tunneling used to exfiltrate data. The tunneling technique, encoding scheme, data reassembly protocol, and exfiltration domain are all unknown. Read `/app/scenario.txt` for incident context.

Produce three deliverables:

**1. Data Recovery** — Identify the DNS tunnel traffic within the pcap, reverse-engineer its subdomain encoding and chunk sequencing protocol (including deduplication of retransmitted queries), and reconstruct the exfiltrated payload. Write the raw bytes to `/app/exfiltrated.bin`.

**2. Structured Analysis** — Write `/app/tunnel_analysis.json` with exactly these fields:
- `tunnel_domain` (string): base domain used for tunneling, excluding any data-carrying subdomain labels
- `total_tunnel_queries` (integer): total tunnel DNS queries including retransmissions
- `unique_chunks` (integer): number of distinct data chunks after deduplication
- `encoding` (string): encoding scheme name for data in subdomain labels (e.g. `"base32"`, `"hex"`)
- `query_type` (string): DNS query type used for tunnel traffic (e.g. `"TXT"`, `"A"`)
- `retransmission_count` (integer): number of duplicate tunnel queries

**3. Detection Engineering** — Write a general-purpose DNS tunnel detector at `/app/detector.py` that works on arbitrary pcap files, not just this one. Interface:
- Accepts a pcap file path as its sole command-line argument
- Prints JSON to stdout: `{"detected_tunnels": [{"domain": "<base_domain>"}, ...]}`
- Must identify tunnel base domains in previously-unseen pcap files using statistical or heuristic analysis of DNS query patterns