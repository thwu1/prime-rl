A BIND9 split-horizon DNS server for `weilburg.corp` is configured under `/etc/bind/` with correct zone data for internal and external views. The server is not running and has no security controls deployed.

Design and deploy a comprehensive DNS security architecture. When finished, `named` must be running on `127.0.0.1:53`, all existing records and split-horizon behavior must be preserved, and `named-checkconf` must pass.

## DNSSEC

All authoritative zones across both views must be signed using BIND9 inline DNSSEC signing. Use ECDSAP256SHA256 (algorithm 13) for all keys. Authenticated denial of existence must use NSEC3 with zero iterations and zero-length salt per RFC 9276. Responses to DNSSEC-aware queries must include valid DNSKEY and RRSIG records.

## Zone Transfer Authentication

All zone transfers (AXFR/IXFR) must require TSIG authentication using an HMAC-SHA256 key named `xfer-key`. Unauthenticated zone transfer requests must be refused for every zone in every view.

## Response Policy Zone

Deploy an RPZ within the internal view to enforce threat-blocking policy:

| Threat domain | Action |
|---|---|
| `malware.evil.test` | NXDOMAIN |
| `phishing.evil.test` | Redirect to sinkhole `10.10.0.99` |
| `*.botnet.evil.test` | NXDOMAIN (wildcard) |

The RPZ must not interfere with resolution of legitimate internal or external domain names.

## Response Rate Limiting

Enable RRL to mitigate DNS amplification attacks, capping at 5 responses-per-second.