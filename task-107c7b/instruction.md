Four candidate TCP-AO (RFC 5925/5926) implementations exist at `/app/candidates/` (`impl_a.py` through `impl_d.py`). Each provides `derive_traffic_key()` and `compute_mac()` functions for the two mandatory algorithm suites (KDF_HMAC_SHA1 + HMAC-SHA-1-96, and KDF_AES_128_CMAC + AES-128-CMAC-96). Some candidates contain subtle cryptographic bugs documented in RFC 9235 Section 8.

A pcap file at `/app/bgp_capture.pcap` contains 8 captured TCP SYN segments from BGP sessions authenticated with TCP-AO. The embedded MACs are authoritative (derived from RFC 9235 test vectors). Connection metadata is at `/app/connections.json`.

Audit all four candidates against the captured traffic. Determine which implementations are correct, which are broken, identify the specific RFC violations in the broken ones, and classify severity. Your ground-truth reference values must be computed independently of any candidate's Python code.

Produce `/app/audit_report.json` conforming to the schema at `/app/audit_schema.json`.