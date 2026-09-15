A security audit of Acme Corp's PKI infrastructure has produced 18 critical findings. The audit report is at `/app/pki/audit_findings.txt` and the existing broken PKI artifacts (keys and certificates) are at `/app/pki/`.

Build a complete remediated PKI hierarchy at `/app/pki-remediated/` that resolves every finding in the audit report. No certificate in the remediated hierarchy may use SHA-1, and all certificate chain paths must pass `openssl verify`.

The remediated hierarchy must be organized as:

```
root/root-ca.{key,crt,crl}
tls-intermediate/tls-intermediate.{key,crt,crl}
tls-intermediate/ocsp-signing.{key,crt}
cs-intermediate/cs-intermediate.{key,crt,crl}
certs/server.{key,crt}          + certs/server-fullchain.pem
certs/codesign.{key,crt}        + certs/codesign-fullchain.pem
certs/client.{key,crt}          + certs/client-fullchain.pem
cross-cert/cross-cert.crt
```

Full-chain PEM bundles must contain at minimum the end-entity certificate concatenated with its issuing intermediate. The cross-certification bridge certificate must be signed by the legacy root's private key at `/app/pki/root-ca.key` and carry the new root's public key, enabling chain validation from the old trust anchor to new end-entity certificates.