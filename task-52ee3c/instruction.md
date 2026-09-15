An authoritative DNS server at `/app/dns_server.py` (startup script `/app/start.sh`) loads zone files from `/app/zones/` and serves queries on port 5300 over UDP and TCP. No DNS libraries (e.g., `dnspython`) may be used — the implementation uses raw sockets and `struct` only.

The server has multiple RFC 1035 and RFC 4592 conformance defects. The zone file `/app/zones/example.test.zone` exercises A, AAAA, NS, MX, CNAME, TXT, SOA, wildcard, and delegation records. Fix all defects in `/app/dns_server.py` and `/app/start.sh` so behavior matches the RFCs.

Known defect categories to investigate:

- **Name compression** (RFC 1035 §4.1.4): Responses must use compression pointers to reduce wire size.
- **Negative responses**: Both NXDOMAIN (RCODE 3) and NODATA (RCODE 0, empty answer) must include the zone SOA in the authority section.
- **CNAME chasing** (RFC 1035 §3.6.2): Querying a type other than CNAME on a CNAME owner must return the CNAME record plus the target's matching records in the answer section.
- **Wildcard synthesis** (RFC 4592): Wildcard matches must synthesize the owner name to the queried name, not return the literal `*.` label.
- **Delegation referrals**: AA flag must be cleared. Authority section contains NS records for the delegated zone. Additional section contains glue A records for those nameservers.
- **Additional section processing**: NS and MX query answers must include glue A/AAAA records for referenced names in the additional section.
- **TCP framing** (RFC 1035 §4.2.2): TCP responses must be prefixed with a two-byte big-endian length.
- **Query logging**: The server must write NDJSON to `/app/dns_query.log` — one JSON object per line with fields: `ts` (ISO 8601), `client` (IP string), `qname`, `qtype` (int), `rcode` (int), `answers` (int count of answer RRs).
- **Zone validation**: `/app/start.sh` must run `named-checkzone` on each zone file before starting the server and exit non-zero if validation fails.