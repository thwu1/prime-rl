A DNS infrastructure using NSD (authoritative server) and Unbound (recursive resolver) has been deployed at `/app/dns/` but is not functioning correctly. All configuration files, zone files, and DNSSEC key material are present in that directory tree.

**Intended operational state:**

- **NSD** (127.0.0.1:5353) serves three zones: `acme-internal.test` (DNSSEC-signed with ECDSAP256SHA256), `113.0.203.in-addr.arpa` (reverse DNS for 203.0.113.0/24), and `evil.test`
- **Unbound** (127.0.0.1:5300) provides validating recursive resolution:
  - DNSSEC validation for `acme-internal.test` — the AD flag must be set in responses to queries with the DO bit
  - Forward lookups for all `acme-internal.test` records including A, MX, SRV, CNAME, and wildcard entries
  - Reverse PTR lookups for addresses in the 203.0.113.0/24 range
  - Private-address response filtering that blocks RFC1918 addresses from DNS answers — `trap.evil.test` (authoritative answer 10.0.0.1) must be blocked while `legit.evil.test` (203.0.113.99) must resolve normally

Start the services using `/app/dns/start.sh`. The infrastructure has multiple configuration defects causing widespread query failures across both servers. Diagnose all issues in the NSD and Unbound configurations and apply the necessary fixes. Both NSD and Unbound must be running and answering queries correctly when you are done.