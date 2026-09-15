# SecureCorp PKI Requirements Specification

## Organization
- Name: SecureCorp
- Location: San Francisco, California, US

## Root Certificate Authority
- Subject: C=US, ST=California, L=San Francisco, O=SecureCorp, OU=PKI Operations, CN=SecureCorp Root CA
- Key algorithm: EC P-384 (secp384r1) — key already generated at private/root-ca.key
- Validity: 10 years (3650 days)
- Digest algorithm: SHA-384
- Basic Constraints: critical, CA:TRUE, pathlen:1
- Key Usage: critical, digitalSignature, cRLSign, keyCertSign
- Certificate path: /app/pki/root-ca/certs/root-ca.crt

## Intermediate Certificate Authority
- Subject: C=US, ST=California, L=San Francisco, O=SecureCorp, OU=Infrastructure, CN=SecureCorp Intermediate CA
- Key algorithm: EC P-384 (secp384r1) — must be generated
- Validity: 5 years (1825 days)
- Signed by: Root CA
- Basic Constraints: critical, CA:TRUE, pathlen:0
- Key Usage: critical, digitalSignature, cRLSign, keyCertSign
- Certificate path: /app/pki/intermediate-ca/certs/intermediate-ca.crt
- Chain file: /app/pki/intermediate-ca/certs/ca-chain.crt (intermediate + root, in order)

## Server Certificate
- Subject CN: web.securecorp.lab
- Subject Alternative Names: DNS:web.securecorp.lab, DNS:www.securecorp.lab, IP:10.0.1.10
- Extended Key Usage: serverAuth
- Validity: 2 years (730 days)
- Signed by: Intermediate CA
- Certificate: /app/pki/intermediate-ca/certs/server/web.securecorp.lab.crt
- Private key: /app/pki/intermediate-ca/private/server/web.securecorp.lab.key

## Client Certificate
- Subject: C=US, ST=California, O=SecureCorp, OU=Engineering, CN=Alice Chen, emailAddress=alice@securecorp.lab
- Subject Alternative Names: email:alice@securecorp.lab
- Extended Key Usage: clientAuth, emailProtection
- Validity: 1 year (365 days)
- Signed by: Intermediate CA
- Certificate: /app/pki/intermediate-ca/certs/client/alice.crt
- Private key: /app/pki/intermediate-ca/private/client/alice.key
- Post-issuance status: REVOKED with reason keyCompromise

## Certificate Revocation List
- Path: /app/pki/intermediate-ca/crl/intermediate-ca.crl
- Must contain the revoked client certificate serial number
- Signed by: Intermediate CA

## File Permission Requirements
- All private keys: mode 0400
- All certificates: mode 0444
- CRL files: mode 0644
