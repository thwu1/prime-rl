#!/usr/bin/env python3
"""Generate randomized deployment parameters for PKI environment at build time."""
import json
import secrets

audit_stamp = secrets.token_hex(4)
b2 = secrets.randbelow(250) + 2
b3 = secrets.randbelow(250) + 2
b4 = secrets.randbelow(250) + 2
server_ip = f"10.{b2}.{b3}.{b4}"

params = {
    "audit_stamp": audit_stamp,
    "server_san_ip": server_ip,
}

with open("/app/pki/deploy_params.json", "w") as f:
    json.dump(params, f, indent=2)

requirements = f"""# SecureCorp PKI Requirements Specification

## Deployment Parameters
- Audit stamp: `{audit_stamp}` (also stored in `/app/pki/deploy_params.json`)
- Every certificate's Organizational Unit (OU) field MUST include the audit stamp as a
  hyphenated suffix. For example, if the base OU is "PKI Operations" and the stamp is
  "{audit_stamp}", the OU becomes "PKI Operations-{audit_stamp}".

## Organization
- Name: SecureCorp
- Location: San Francisco, California, US

## Root Certificate Authority
- Subject: C=US, ST=California, L=San Francisco, O=SecureCorp, OU=PKI Operations-{audit_stamp}, CN=SecureCorp Root CA
- Key algorithm: EC P-384 (secp384r1) -- key already generated at private/root-ca.key
- Validity: 10 years (3650 days)
- Digest algorithm: SHA-384
- Basic Constraints: critical, CA:TRUE, pathlen:1
- Key Usage: critical, digitalSignature, cRLSign, keyCertSign
- Certificate path: /app/pki/root-ca/certs/root-ca.crt

## Intermediate Certificate Authority
- Subject: C=US, ST=California, L=San Francisco, O=SecureCorp, OU=Infrastructure-{audit_stamp}, CN=SecureCorp Intermediate CA
- Key algorithm: EC P-384 (secp384r1) -- must be generated
- Validity: 5 years (1825 days)
- Signed by: Root CA
- Basic Constraints: critical, CA:TRUE, pathlen:0
- Key Usage: critical, digitalSignature, cRLSign, keyCertSign
- Certificate path: /app/pki/intermediate-ca/certs/intermediate-ca.crt
- Chain file: /app/pki/intermediate-ca/certs/ca-chain.crt (intermediate + root, in order)

## Server Certificate
- Subject: C=US, ST=California, O=SecureCorp, OU=WebOps-{audit_stamp}, CN=web.securecorp.lab
- Subject Alternative Names: DNS:web.securecorp.lab, DNS:www.securecorp.lab, IP:{server_ip}
- Extended Key Usage: serverAuth
- Validity: 2 years (730 days)
- Signed by: Intermediate CA
- Certificate: /app/pki/intermediate-ca/certs/server/web.securecorp.lab.crt
- Private key: /app/pki/intermediate-ca/private/server/web.securecorp.lab.key

## Client Certificate
- Subject: C=US, ST=California, O=SecureCorp, OU=Engineering-{audit_stamp}, CN=Alice Chen, emailAddress=alice@securecorp.lab
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
"""

with open("/app/pki/requirements.md", "w") as f:
    f.write(requirements)
