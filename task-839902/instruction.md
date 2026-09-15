A PKI infrastructure at `/app/pki/` was deployed using OpenSSL 3.5.0 (`/usr/local/bin/openssl`) targeting NSA CNSA 2.0 compliance. It has never been formally audited. The infrastructure includes a Root CA, Intermediate CA, and several end-entity certificates, but security review has flagged potential compliance and correctness issues.

Perform a comprehensive CNSA 2.0 compliance audit of the entire certificate hierarchy. Identify all algorithm, extension, and operational violations. Remediate every issue and deliver a fully compliant, operational PKI.

## Audit Report

Write a detailed audit report to `/app/pki/audit-report.txt`. For each finding: state what was observed, why it violates CNSA 2.0 or X.509 correctness requirements, and what remediation was applied.

## PKI Requirements

After remediation, the following certificates must exist, pass full chain validation, and be fully CNSA 2.0 compliant:

- **Root CA** — `/app/pki/root-ca/certs/root-ca.crt`, CN=`PQC Root CA`, `basicConstraints = critical, CA:TRUE` (no pathlen limit), `keyUsage = critical, digitalSignature, cRLSign, keyCertSign`
- **Intermediate CA** — `/app/pki/intermediate-ca/certs/intermediate-ca.crt`, CN=`PQC Intermediate CA`, `basicConstraints = critical, CA:TRUE, pathlen:0`, signed by Root CA
- **Server cert** — `/app/pki/intermediate-ca/certs/server.crt`, CN=`server.pqc.lab`, SANs: `DNS:server.pqc.lab`, `DNS:*.pqc.lab`, `IP:10.0.0.1`, `extendedKeyUsage = serverAuth`
- **Client cert** — `/app/pki/intermediate-ca/certs/client.crt`, CN=`client@pqc.lab`, `extendedKeyUsage = clientAuth, emailProtection`
- **OCSP cert** — `/app/pki/intermediate-ca/certs/ocsp.crt`, CN=`OCSP Responder`, `extendedKeyUsage = critical, OCSPSigning`

All end-entity certificates must have `basicConstraints = CA:FALSE` and be signed by the Intermediate CA. OpenSSL CA configs must be at `/app/pki/root-ca/openssl.cnf` and `/app/pki/intermediate-ca/openssl.cnf`.

## Revocation

A CRL must exist at `/app/pki/intermediate-ca/crl/intermediate-ca.crl` containing at least one revoked certificate serial number.

## Chain Bundle

Assemble the CA chain at `/app/pki/certs/ca-chain.crt` (Intermediate CA + Root CA).

## TLS 1.3 Verification

Demonstrate a successful TLS 1.3 handshake with **X25519MLKEM768** hybrid key exchange using the server certificate. Save s_client output (stdout + stderr) to `/app/pki/tls-test-result.txt`. The output must contain `Verify return code: 0` and show `X25519MLKEM768` group negotiation.