#!/bin/bash
set -e

# Use permissive config to allow SHA-1 signing (Ubuntu 24.04 default SECLEVEL=2 blocks it)
export OPENSSL_CONF=/tmp/legacy_openssl.cnf

PKI="/app/pki"
mkdir -p "$PKI"

# ================================================================
# Root CA - RSA 2048, SHA-1 (deliberately weak for audit scenario)
# ================================================================
openssl genrsa -out "$PKI/root-ca.key" 2048 2>/dev/null
openssl req -new -x509 -sha1 -key "$PKI/root-ca.key" -out "$PKI/root-ca.crt" -days 7300 \
  -subj "/CN=Legacy Root CA/O=Acme Corp/C=US"

# ================================================================
# Intermediate CA - RSA 2048, SHA-1, no pathlen, no name constraints
# ================================================================
openssl genrsa -out "$PKI/intermediate-ca.key" 2048 2>/dev/null
openssl req -new -sha1 -key "$PKI/intermediate-ca.key" -out /tmp/int.csr \
  -subj "/CN=Acme Intermediate CA/O=Acme Corp/C=US"

printf "basicConstraints = CA:TRUE\nkeyUsage = keyCertSign\n" > /tmp/int_ext.cnf
openssl x509 -req -sha1 -in /tmp/int.csr \
  -CA "$PKI/root-ca.crt" -CAkey "$PKI/root-ca.key" \
  -CAcreateserial -out "$PKI/intermediate-ca.crt" -days 3650 \
  -extfile /tmp/int_ext.cnf 2>/dev/null

# ================================================================
# Server TLS cert - no SAN, wrong keyUsage (missing digitalSignature)
# ================================================================
openssl genrsa -out "$PKI/server.key" 2048 2>/dev/null
openssl req -new -key "$PKI/server.key" -out /tmp/srv.csr \
  -subj "/CN=www.example.com/O=Acme Corp"

printf "basicConstraints = CA:FALSE\nkeyUsage = keyEncipherment\nextendedKeyUsage = serverAuth\n" > /tmp/srv_ext.cnf
openssl x509 -req -sha256 -in /tmp/srv.csr \
  -CA "$PKI/intermediate-ca.crt" -CAkey "$PKI/intermediate-ca.key" \
  -CAcreateserial -out "$PKI/server.crt" -days 365 \
  -extfile /tmp/srv_ext.cnf 2>/dev/null

# ================================================================
# Code signing cert - wrong EKU (serverAuth instead of codeSigning)
# ================================================================
openssl genrsa -out "$PKI/codesign.key" 2048 2>/dev/null
openssl req -new -key "$PKI/codesign.key" -out /tmp/cs.csr \
  -subj "/CN=Acme Code Signing/O=Acme Corp"

printf "basicConstraints = CA:FALSE\nkeyUsage = digitalSignature\nextendedKeyUsage = serverAuth\n" > /tmp/cs_ext.cnf
openssl x509 -req -sha256 -in /tmp/cs.csr \
  -CA "$PKI/intermediate-ca.crt" -CAkey "$PKI/intermediate-ca.key" \
  -CAcreateserial -out "$PKI/codesign.crt" -days 365 \
  -extfile /tmp/cs_ext.cnf 2>/dev/null

# ================================================================
# Client cert - no email SAN, minimal validity
# ================================================================
openssl genrsa -out "$PKI/client.key" 2048 2>/dev/null
openssl req -new -key "$PKI/client.key" -out /tmp/cl.csr \
  -subj "/CN=user@example.com/O=Acme Corp"

printf "basicConstraints = CA:FALSE\nkeyUsage = digitalSignature\nextendedKeyUsage = clientAuth\n" > /tmp/cl_ext.cnf
openssl x509 -req -sha256 -in /tmp/cl.csr \
  -CA "$PKI/intermediate-ca.crt" -CAkey "$PKI/intermediate-ca.key" \
  -CAcreateserial -out "$PKI/client.crt" -days 30 \
  -extfile /tmp/cl_ext.cnf 2>/dev/null

# ================================================================
# Cleanup temp files
# ================================================================
rm -f /tmp/*.csr /tmp/*_ext.cnf

# ================================================================
# Audit findings document
# ================================================================
cat > "$PKI/audit_findings.txt" << 'AUDIT'
PKI SECURITY AUDIT FINDINGS - CRITICAL
=======================================

CRITICAL FINDINGS:
1.  Root CA uses RSA-2048 key (minimum ECDSA P-384 required per policy)
2.  Root CA certificate signed with SHA-1 (deprecated, collision attacks demonstrated)
3.  Intermediate CA signed with SHA-1 (deprecated)
4.  Intermediate CA missing pathlen constraint (allows unauthorized sub-CA creation)
5.  Intermediate CA missing name constraints (can issue certs for any domain)
6.  Intermediate CA keyUsage missing cRLSign
7.  No CRL distribution points on any certificate
8.  No OCSP responder URIs configured
9.  No Authority Key Identifier extensions on issued certificates
10. Server TLS certificate missing Subject Alternative Name extension
11. Server TLS certificate keyUsage has only keyEncipherment (missing digitalSignature for ECDHE)
12. Code signing certificate has serverAuth EKU instead of codeSigning EKU
13. Client certificate missing email in SAN (email only in subject CN, no RFC822Name SAN)
14. Client certificate has only 30-day validity (insufficient)
15. All certificates use RSA-2048 keys (should use ECDSA P-256 or better)
16. No cross-certification plan for migration to replacement PKI hierarchy
17. No OCSP signing delegation infrastructure
18. Single intermediate CA serves all purposes (should separate TLS from code signing)

REQUIRED REMEDIATION:
Build a complete replacement PKI hierarchy at /app/pki-remediated/ addressing all findings above.
AUDIT
