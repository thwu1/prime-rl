#!/bin/bash
set -e


OPENSSL=/usr/local/bin/openssl
PKI=/app/pki

echo "=== Phase 1: Auditing existing PKI for CNSA 2.0 compliance ==="

# Inspect current state
ROOT_SIG=$($OPENSSL x509 -in "$PKI/root-ca/certs/root-ca.crt" -noout -text | grep "Signature Algorithm" | head -1 | sed 's/.*: //')
ROOT_KEY=$($OPENSSL x509 -in "$PKI/root-ca/certs/root-ca.crt" -noout -text | grep "Public Key Algorithm" | sed 's/.*: //')

INT_SIG=$($OPENSSL x509 -in "$PKI/intermediate-ca/certs/intermediate-ca.crt" -noout -text | grep "Signature Algorithm" | head -1 | sed 's/.*: //')
INT_KEY=$($OPENSSL x509 -in "$PKI/intermediate-ca/certs/intermediate-ca.crt" -noout -text | grep "Public Key Algorithm" | sed 's/.*: //')

SRV_TEXT=$($OPENSSL x509 -in "$PKI/intermediate-ca/certs/server.crt" -noout -text)
SRV_KU=$(echo "$SRV_TEXT" | grep -A1 "X509v3 Key Usage" | tail -1 | sed 's/^ *//')
SRV_SANS=$(echo "$SRV_TEXT" | grep -A10 "Subject Alternative Name" | grep -E "DNS:|IP:" | sed 's/^ *//' || echo "NONE")

CLT_TEXT=$($OPENSSL x509 -in "$PKI/intermediate-ca/certs/client.crt" -noout -text)
CLT_EKU=$(echo "$CLT_TEXT" | grep -A1 "Extended Key Usage" | tail -1 | sed 's/^ *//')

OCSP_EXISTS="NO"
[ -f "$PKI/intermediate-ca/certs/ocsp.crt" ] && OCSP_EXISTS="YES"

CHAIN_EXISTS="NO"
[ -f "$PKI/certs/ca-chain.crt" ] && CHAIN_EXISTS="YES"

CRL_REVOKED=$($OPENSSL crl -in "$PKI/intermediate-ca/crl/intermediate-ca.crl" -noout -text 2>/dev/null | grep -c "Serial Number:" || echo "0")

TLS_EXISTS="NO"
[ -f "$PKI/tls-test-result.txt" ] && TLS_EXISTS="YES"

# Write audit report
cat > "$PKI/audit-report.txt" << AUDIT_EOF
============================================================
CNSA 2.0 PKI Compliance Audit Report
Date: $(date)
Auditor: Automated compliance scanner
============================================================

FINDING 1: Root CA uses non-compliant signature algorithm (CRITICAL)
  Observed: Root CA key algorithm = $ROOT_KEY, signature algorithm = $ROOT_SIG
  Expected: CNSA 2.0 (draft-jenkins-cnsa2-pkix-profile) mandates ML-DSA-87 (mldsa87)
            for ALL digital signatures. ML-DSA-65 (mldsa65) is FIPS 204 Level 3,
            but CNSA 2.0 requires Level 5 (ML-DSA-87) exclusively.
  Impact: CRITICAL - The entire chain of trust is rooted in a non-compliant algorithm.
          All certificates downstream inherit this violation at their signing link.
  Remediation: Regenerate Root CA private key with ML-DSA-87 algorithm.
               Re-create self-signed Root CA certificate. Re-sign Intermediate CA.

FINDING 2: Intermediate CA certificate signed with non-compliant algorithm (HIGH)
  Observed: Intermediate CA cert Signature Algorithm = $INT_SIG (from Root CA)
            Intermediate CA own key algorithm = $INT_KEY (compliant)
  Impact: HIGH - The Root-to-Intermediate signing link uses mldsa65, violating CNSA 2.0.
          Even though the Intermediate CA's own key is ML-DSA-87, its certificate's
          signature was made with the Root CA's ML-DSA-65 key.
  Remediation: After fixing Root CA, re-sign Intermediate CA CSR with corrected Root.

FINDING 3: Server certificate keyUsage includes keyEncipherment (MEDIUM)
  Observed: Server cert Key Usage = $SRV_KU
  Issue: keyEncipherment is semantically invalid for ML-DSA keys. ML-DSA (FIPS 204) is
         a pure digital signature algorithm - it cannot perform key encipherment or key
         transport operations. Including keyEncipherment violates X.509 key usage
         semantics and misrepresents the key's cryptographic capabilities.
  Remediation: Remove keyEncipherment from server_cert keyUsage in Intermediate CA config.
               Re-issue server certificate with keyUsage = critical, digitalSignature only.

FINDING 4: Server certificate missing Subject Alternative Names (MEDIUM)
  Observed SANs: $SRV_SANS
  Missing: DNS:*.pqc.lab (wildcard subdomain), IP:10.0.0.1 (internal addressing)
  Impact: Server cert cannot match wildcard subdomains or IP-based connections.
  Remediation: Add DNS.2 = *.pqc.lab and IP.1 = 10.0.0.1 to server_alt_names in config.

FINDING 5: Client certificate has incorrect Extended Key Usage (HIGH)
  Observed: Client cert EKU = $CLT_EKU
  Expected: clientAuth, emailProtection
  Impact: Client cert configured with serverAuth instead of clientAuth and emailProtection.
          Cannot be used for TLS client authentication or S/MIME email operations.
  Remediation: Fix client_cert extension section EKU to clientAuth, emailProtection.

FINDING 6: Missing OCSP signing certificate (MEDIUM)
  OCSP certificate present: $OCSP_EXISTS
  Impact: No OCSP responder can operate without a dedicated OCSP signing certificate.
  Remediation: Generate OCSP key, create CSR, issue cert with EKU = critical, OCSPSigning.

FINDING 7: Empty CRL - no revocations recorded (LOW)
  Revoked entries in CRL: $CRL_REVOKED
  Impact: Revocation infrastructure is non-operational.
  Remediation: Revoke non-compliant certificates and regenerate CRL.

FINDING 8: Missing CA chain bundle (MEDIUM)
  Chain bundle at /app/pki/certs/ca-chain.crt: $CHAIN_EXISTS
  Impact: Applications cannot perform chain validation without manual CA file specification.
  Remediation: Concatenate Intermediate CA + Root CA certificates into chain bundle.

FINDING 9: No TLS verification performed (LOW)
  TLS test result: $TLS_EXISTS
  Impact: No evidence that PKI supports TLS 1.3 with hybrid PQC key exchange.
  Remediation: Perform TLS 1.3 handshake test with X25519MLKEM768 and record results.

============================================================
TOTAL FINDINGS: 9 (2 Critical/High algorithm issues, 4 Medium, 3 Low/Operational)
============================================================
AUDIT_EOF

echo "Audit report written to $PKI/audit-report.txt"

# ===================================================================
echo "=== Phase 2: Regenerating Root CA with ML-DSA-87 ==="
# ===================================================================

# Backup old Root CA artifacts
cp "$PKI/root-ca/private/root-ca.key" "$PKI/root-ca/private/root-ca.key.bak"
cp "$PKI/root-ca/certs/root-ca.crt" "$PKI/root-ca/certs/root-ca.crt.bak"

# Generate new Root CA key with correct CNSA 2.0 algorithm
$OPENSSL genpkey -algorithm mldsa87 \
    -out "$PKI/root-ca/private/root-ca.key"
chmod 400 "$PKI/root-ca/private/root-ca.key"

# Create new self-signed Root CA certificate
$OPENSSL req -config "$PKI/root-ca/openssl.cnf" \
    -new -x509 \
    -key "$PKI/root-ca/private/root-ca.key" \
    -extensions v3_ca \
    -days 3650 \
    -out "$PKI/root-ca/certs/root-ca.crt"

echo "Root CA regenerated with ML-DSA-87"
$OPENSSL x509 -in "$PKI/root-ca/certs/root-ca.crt" -noout -subject -issuer

# ===================================================================
echo "=== Phase 3: Re-signing Intermediate CA certificate ==="
# ===================================================================

# The Intermediate CA's own key (ML-DSA-87) is correct - only the cert needs re-signing
# The CSR at intermediate-ca/csr/intermediate-ca.csr can be reused
$OPENSSL ca -config "$PKI/root-ca/openssl.cnf" \
    -extensions v3_intermediate_ca \
    -days 1825 \
    -notext -batch \
    -in "$PKI/intermediate-ca/csr/intermediate-ca.csr" \
    -out "$PKI/intermediate-ca/certs/intermediate-ca.crt"

# Verify chain
$OPENSSL verify -CAfile "$PKI/root-ca/certs/root-ca.crt" \
    "$PKI/intermediate-ca/certs/intermediate-ca.crt"
echo "Intermediate CA re-signed successfully"

# ===================================================================
echo "=== Phase 4: Fixing Intermediate CA openssl.cnf ==="
# ===================================================================

# Rewrite the config with corrected extension sections:
# - server_cert: remove keyEncipherment, add wildcard SAN and IP SAN
# - client_cert: fix EKU to clientAuth, emailProtection
cat > "$PKI/intermediate-ca/openssl.cnf" << 'INTCFG'
[ca]
default_ca = CA_default

[CA_default]
dir               = /app/pki/intermediate-ca
certs             = $dir/certs
crl_dir           = $dir/crl
new_certs_dir     = $dir/newcerts
database          = $dir/index.txt
serial            = $dir/serial
private_key       = $dir/private/intermediate-ca.key
certificate       = $dir/certs/intermediate-ca.crt
crlnumber         = $dir/crlnumber
crl               = $dir/crl/intermediate-ca.crl
crl_extensions    = crl_ext
default_crl_days  = 30
default_md        = sha512
default_days      = 730
preserve          = no
policy            = policy_loose

[policy_loose]
countryName             = optional
stateOrProvinceName     = optional
localityName            = optional
organizationName        = optional
organizationalUnitName  = optional
commonName              = supplied
emailAddress            = optional

[req]
distinguished_name = req_distinguished_name
string_mask        = utf8only
default_md         = sha512
prompt             = no

[req_distinguished_name]
C  = US
ST = Virginia
L  = Arlington
O  = PQC Corp
OU = PKI Operations
CN = PQC Intermediate CA

[server_cert]
basicConstraints       = CA:FALSE
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
keyUsage               = critical, digitalSignature
extendedKeyUsage       = serverAuth
subjectAltName         = @server_alt_names

[server_alt_names]
DNS.1 = server.pqc.lab
DNS.2 = *.pqc.lab
IP.1  = 10.0.0.1

[client_cert]
basicConstraints       = CA:FALSE
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
keyUsage               = critical, nonRepudiation, digitalSignature
extendedKeyUsage       = clientAuth, emailProtection

[ocsp_cert]
basicConstraints       = CA:FALSE
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
keyUsage               = critical, digitalSignature
extendedKeyUsage       = critical, OCSPSigning

[crl_ext]
authorityKeyIdentifier = keyid:always
INTCFG

echo "Intermediate CA config corrected"

# ===================================================================
echo "=== Phase 5: Revoking old non-compliant end-entity certificates ==="
# ===================================================================

# Revoke the old server cert (wrong keyUsage, missing SANs)
$OPENSSL ca -config "$PKI/intermediate-ca/openssl.cnf" \
    -revoke "$PKI/intermediate-ca/certs/server.crt" \
    -crl_reason superseded || true

# Revoke the old client cert (wrong EKU)
$OPENSSL ca -config "$PKI/intermediate-ca/openssl.cnf" \
    -revoke "$PKI/intermediate-ca/certs/client.crt" \
    -crl_reason superseded || true

echo "Old non-compliant certificates revoked"

# ===================================================================
echo "=== Phase 6: Re-issuing end-entity certificates ==="
# ===================================================================

# Re-issue server certificate with corrected extensions (using existing CSR)
$OPENSSL ca -config "$PKI/intermediate-ca/openssl.cnf" \
    -extensions server_cert \
    -days 365 \
    -notext -batch \
    -in "$PKI/intermediate-ca/csr/server.csr" \
    -out "$PKI/intermediate-ca/certs/server.crt"
echo "Server cert re-issued with correct keyUsage and SANs"

# Re-issue client certificate with corrected EKU (using existing CSR)
$OPENSSL ca -config "$PKI/intermediate-ca/openssl.cnf" \
    -extensions client_cert \
    -days 365 \
    -notext -batch \
    -in "$PKI/intermediate-ca/csr/client.csr" \
    -out "$PKI/intermediate-ca/certs/client.crt"
echo "Client cert re-issued with correct EKU (clientAuth, emailProtection)"

# Issue OCSP signing certificate (new key + CSR)
$OPENSSL genpkey -algorithm mldsa87 \
    -out "$PKI/intermediate-ca/private/ocsp.key"
chmod 400 "$PKI/intermediate-ca/private/ocsp.key"

$OPENSSL req -config "$PKI/intermediate-ca/openssl.cnf" \
    -new \
    -key "$PKI/intermediate-ca/private/ocsp.key" \
    -subj "/C=US/ST=Virginia/L=Arlington/O=PQC Corp/OU=PKI Operations/CN=OCSP Responder" \
    -out "$PKI/intermediate-ca/csr/ocsp.csr"

$OPENSSL ca -config "$PKI/intermediate-ca/openssl.cnf" \
    -extensions ocsp_cert \
    -days 365 \
    -notext -batch \
    -in "$PKI/intermediate-ca/csr/ocsp.csr" \
    -out "$PKI/intermediate-ca/certs/ocsp.crt"
echo "OCSP signing cert issued"

# ===================================================================
echo "=== Phase 7: CRL and chain bundle ==="
# ===================================================================

# Generate CRL (now contains the revoked old server + client certs)
$OPENSSL ca -config "$PKI/intermediate-ca/openssl.cnf" \
    -gencrl \
    -out "$PKI/intermediate-ca/crl/intermediate-ca.crl"
echo "CRL generated with revoked entries"

# Assemble CA chain bundle (Intermediate + Root)
cat "$PKI/intermediate-ca/certs/intermediate-ca.crt" \
    "$PKI/root-ca/certs/root-ca.crt" \
    > "$PKI/certs/ca-chain.crt"

# Verify all certs against chain
$OPENSSL verify -CAfile "$PKI/certs/ca-chain.crt" \
    "$PKI/intermediate-ca/certs/server.crt"
$OPENSSL verify -CAfile "$PKI/certs/ca-chain.crt" \
    "$PKI/intermediate-ca/certs/client.crt"
$OPENSSL verify -CAfile "$PKI/certs/ca-chain.crt" \
    "$PKI/intermediate-ca/certs/ocsp.crt"
echo "All certificates verified against chain"

# ===================================================================
echo "=== Phase 8: TLS 1.3 with X25519MLKEM768 hybrid key exchange ==="
# ===================================================================

$OPENSSL s_server \
    -cert "$PKI/intermediate-ca/certs/server.crt" \
    -key "$PKI/intermediate-ca/private/server.key" \
    -CAfile "$PKI/certs/ca-chain.crt" \
    -port 14433 \
    -tls1_3 \
    -groups X25519MLKEM768:X25519 \
    -www &
SERVER_PID=$!
sleep 3

echo "Q" | $OPENSSL s_client \
    -connect localhost:14433 \
    -tls1_3 \
    -groups X25519MLKEM768 \
    -CAfile "$PKI/certs/ca-chain.crt" \
    > "$PKI/tls-test-result.txt" 2>&1 || true

kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true

echo "TLS test result:"
grep -E "(Protocol|Verify|Temp Key|Server public key)" "$PKI/tls-test-result.txt" || true

echo ""
echo "=== CNSA 2.0 PKI Remediation Complete ==="
echo "All 9 audit findings have been remediated."
