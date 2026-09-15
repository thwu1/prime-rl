During an incident response engagement, your team captured DNS resolver logs from the corporate network at `/app/dns_queries.log`. Threat intelligence indicates that a compromised host was used to exfiltrate sensitive data over covert DNS channels. The attacker used multiple encoding schemes to tunnel stolen data through DNS query subdomain labels, blending the exfiltration traffic with thousands of legitimate DNS queries.

An initial triage report is available at `/app/incident_report.txt`.

Your objectives:

1. Analyze the DNS query log to identify all domains used as exfiltration channels (there are exactly 3).
2. For each exfiltration channel, determine the encoding scheme used, extract all query payloads in the correct sequence order, and decode the original exfiltrated data.
3. One of the channels uses a multi-layer encoding: a byte-level XOR cipher applied before the outer encoding. Recover the XOR key.
4. Write your findings to `/app/results.json` in the following format:

```json
{
  "exfil_domains": ["domain1.example.com", "domain2.example.com", "domain3.example.com"],
  "decoded_data_sha256": {
    "domain1.example.com": "<sha256 hex digest of decoded raw bytes>",
    "domain2.example.com": "<sha256 hex digest of decoded raw bytes>",
    "domain3.example.com": "<sha256 hex digest of decoded raw bytes>"
  },
  "xor_key_hex": "<hex string of the XOR key bytes>"
}
```

The SHA256 digests must be computed over the fully decoded original plaintext bytes for each channel. The `xor_key_hex` is the hex representation of the repeating XOR key bytes (e.g., `"ab01ff"`).

**Note:** The log contains distractor domains with unusual subdomain patterns (CDN identifiers, UUIDs, base64-like cache keys) that are not exfiltration. Legitimate noise must be distinguished from actual covert channels. Sequence numbers are embedded in the query names to enable correct reassembly.