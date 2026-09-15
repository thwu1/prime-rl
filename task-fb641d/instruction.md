A DNS authoritative server is deployed at `/app/dns_server.py`, serving zone data from `/app/zones/example.com.zone` on UDP port 1053:

```
python3 /app/dns_server.py --zone /app/zones/example.com.zone --port 1053
```

The server has multiple protocol violations against RFC 1035 and RFC 6891 that cause interoperability failures with production DNS resolvers. Some violations corrupt wire-level encoding of record data; others affect query processing logic for certain resolution scenarios.

Your task is to audit the server's implementation against the relevant RFC specifications, identify every protocol violation, fix each one in the source code, and produce a structured compliance report.

The zone includes A, AAAA, NS, MX, SOA, TXT, SRV, and CNAME records across the apex and several subdomains, including alias chains and wildcard entries. The corrected server must handle the zone's full record set with standards-compliant wire encoding and query processing as defined by RFC 1035 and RFC 6891. Test your fixes by sending DNS queries against the running server and verifying that responses conform to the wire format and semantics specified in those RFCs.

## Compliance Report

Write `/app/compliance_report.json` — a JSON array where each element is an object with these fields:

- `"violation"`: concise description of the non-conformance
- `"rfc"`: the RFC violated (e.g. `"RFC 1035"`)
- `"section"`: relevant section number (e.g. `"4.3.2"`)
- `"severity"`: one of `"critical"`, `"major"`, or `"minor"`
- `"fix_description"`: what you changed to remediate the violation

The server contains at least four distinct protocol violations. Document all of them.

Write the corrected server to `/app/dns_server.py` and the compliance report to `/app/compliance_report.json`.