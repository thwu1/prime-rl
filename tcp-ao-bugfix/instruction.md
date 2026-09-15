`/app/packet_dump.txt` contains 16 raw IP packets (hex-encoded, one per line) captured from TCP connections authenticated with TCP Authentication Option (TCP-AO, RFC 5925). The packets are unlabeled and shuffled, spanning 8 distinct TCP sessions over both IPv4 and IPv6.

`/app/config.json` provides the shared master key and TCP-AO KeyIDs. `/app/aes_cmac.py` provides a correct AES-128-CMAC (RFC 4493) implementation as a cryptographic building block.

Each session uses one of the two mandatory TCP-AO cryptographic algorithm suites, with either options-included or options-excluded MAC coverage. These parameters are unknown and must be determined forensically from the packet data.

Create `/app/tcp_ao_auditor.py` that analyzes all packets and produces three files:

**`/app/audit.json`** — structured JSON audit report:

```json
{
  "sessions": [
    {
      "client_addr": "...",
      "server_addr": "...",
      "client_port": 12345,
      "server_port": 179,
      "ip_version": 4,
      "kdf_algorithm": "HMAC-SHA1 or AES-128-CMAC",
      "covers_options": true,
      "client_isn": "hex-without-0x-prefix",
      "server_isn": "hex-without-0x-prefix",
      "traffic_keys": {
        "client_syn": "hex",
        "server_synack": "hex"
      },
      "packets": [
        {"type": "SYN", "direction": "client", "mac_valid": true, "mac_hex": "hex"},
        {"type": "SYN-ACK", "direction": "server", "mac_valid": true, "mac_hex": "hex"}
      ]
    }
  ],
  "total_packets": 16,
  "total_valid": 16,
  "total_invalid": 0
}
```

**`/app/validated.pcap`** — valid libpcap-format file (LINKTYPE_RAW=101) containing all 16 packets.

**`/app/tshark_verify.txt`** — output from running `tshark` on the generated pcap, confirming TCP-AO option presence.