Your incident response team has flagged a compromised workstation. Network monitoring captured DNS traffic during the breach window, and forensic imaging preserved select artifacts from the host filesystem. All evidence has been staged at `/app/evidence/`.

Available evidence:
- `/app/evidence/traffic.pcap` -- Full packet capture containing a mix of legitimate and suspicious DNS traffic
- `/app/evidence/workstation/` -- Filesystem artifacts recovered from the compromised host

An insider used a DNS-based covert channel to exfiltrate sensitive data. Your objectives:

1. **Recover** the exfiltrated plaintext data in its entirety
2. **Assess** the attacker's operational security -- identify at least 4 specific weaknesses that made detection or recovery possible
3. **Build** a detection engine that can identify DNS tunnel queries in arbitrary traffic, not just from this specific incident

Write your findings to `/app/results/`:
- `tunnel_domain.txt` -- The base domain used for DNS tunneling (no trailing dot, no trailing newline)
- `packet_count.txt` -- Total number of DNS queries that carried exfiltrated data (integer, no trailing newline)
- `exfiltrated.txt` -- The complete recovered plaintext (no trailing newline)
- `checksum.txt` -- SHA256 hex digest of the recovered plaintext (no trailing newline)
- `assessment.txt` -- Security assessment identifying at least 4 specific weaknesses in the attacker's operational security
- `detector.py` -- Python module implementing a function `detect(query: str) -> bool` that returns `True` for suspected DNS tunnel queries. Must achieve precision >= 0.90 and recall >= 0.85 against diverse tunnel patterns.