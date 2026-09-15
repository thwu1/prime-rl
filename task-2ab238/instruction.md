An enterprise PKI deployment at `/app/pki/` has failed a third-party security compliance audit. The directory contains the organization's certificate authority hierarchy, leaf certificates, private key material, auxiliary cryptographic parameters, and a production nginx TLS configuration. The auditors flagged numerous deficiencies spanning cryptographic strength, X.509 semantics, cross-artifact integrity, certificate path validation, and transport security — but left without producing a detailed report.

Complete the assessment and remediation.

## Deliverables

**`/app/audit_report.json`** — Forensic analysis documenting every security deficiency across all artifacts in `/app/pki/`. Required format:

```json
{"findings": [{"file": "<filename in /app/pki/>", "issue": "<description>", "severity": "critical|high|medium|low"}, ...]}
```

The report must be exhaustive: issues exist at the level of individual certificates, across related artifacts, in the cryptographic parameter files, and in the TLS transport configuration.

**`/app/remediated/`** — A production-grade PKI deployment that resolves every identified deficiency:

- `root-ca.pem` / `root-ca.key`
- `intermediate-ca.pem` / `intermediate-ca.key`
- `server.pem` / `server.key` (must serve `server.acmecorp.internal`)
- `client.pem` / `client.key`
- `chain.pem` (full trust chain)
- `tls.conf` (hardened nginx TLS server block)
- `ocsp_setup.sh` (executable OCSP responder bootstrap)

All remediated artifacts must conform to RFC 5280, NIST SP 800-57, and CA/Browser Forum Baseline Requirements.