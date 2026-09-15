A packet capture at `/app/captures/dns_traffic.pcap` contains DNS responses from an authoritative server for the `services.lab.` domain, mixed with noise traffic (queries, other domains, error responses). The `tshark` tool is available for pcap analysis. Extract the DNS records for `services.lab.` from this capture and generate a BIND-format zone file at `/app/zones/services.lab.zone`.

Implement an authoritative DNS server at `/app/dns_server.py` that loads all `.zone` files from `/app/zones/` and answers DNS queries on UDP and TCP port 5353.

The server must:

- Parse BIND zone files including `$ORIGIN`, `$TTL` directives, multi-line SOA records with parentheses, relative-to-absolute name resolution, and the `@` origin shorthand
- Support record types: A, AAAA, NS, CNAME, SOA, MX, TXT
- Encode DNS responses in correct wire format per RFC 1035
- Follow CNAME chains — include all intermediate CNAME records plus the final target record in the answer section
- Handle wildcard records (`*.subdomain` matching single-label substitution)
- Return NXDOMAIN (rcode 3) for non-existent names, NOERROR (rcode 0) with empty answer when name exists but queried type is absent, and REFUSED (rcode 5) or NXDOMAIN for names outside loaded zones
- Set QR and AA flags in all responses
- Perform case-insensitive name matching
- Include glue A records in the additional section for MX responses
- Support multi-label subdomains (e.g., `sub.deep.example.com`)
- Support EDNS(0) per RFC 6891: when a query includes an OPT pseudo-record in the additional section, parse it and include a server OPT record in the response advertising a 4096-byte UDP payload size; set the TC (truncation) flag when the UDP response would exceed the smaller of the client's advertised payload size and 4096 bytes; do not include an OPT record in responses to non-EDNS queries
- Accept DNS queries over TCP per RFC 1035 §4.2.2: listen on the same port, handle the 2-byte length-prefix framing, and return full non-truncated responses
- Auto-discover and load all `.zone` files from `/app/zones/` on startup

Two zone files are already present at `/app/zones/example.com.zone` and `/app/zones/internal.test.zone`.