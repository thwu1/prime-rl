#!/usr/bin/env bash

set -euo pipefail

PKI=/app/pki

###############################################################################
# Read deployment DNA parameters
###############################################################################

STAMP=$(python3 -c "import json; print(json.load(open('$PKI/deploy_params.json'))['audit_stamp'])")
SERVER_IP=$(python3 -c "import json; print(json.load(open('$PKI/deploy_params.json'))['server_san_ip'])")

###############################################################################
# 1. Fix Root CA openssl.cnf — three structural errors + OU stamp
###############################################################################

# Error 1: default_md = md5 in CA_default → sha384
sed -i 's/default_md        = md5/default_md        = sha384/' \
    "$PKI/root-ca/openssl.cnf"

# Error 2: basicConstraints CA:FALSE in v3_ca → CA:TRUE, pathlen:1
sed -i 's/basicConstraints = critical, CA:FALSE/basicConstraints = critical, CA:TRUE, pathlen:1/' \
    "$PKI/root-ca/openssl.cnf"

# Error 3: keyUsage missing cRLSign, keyCertSign in v3_ca
sed -i 's/^keyUsage = critical, digitalSignature$/keyUsage = critical, digitalSignature, cRLSign, keyCertSign/' \
    "$PKI/root-ca/openssl.cnf"

# DNA: Append audit stamp to OU in req_distinguished_name
sed -i "s/organizationalUnitName          = PKI Operations/organizationalUnitName          = PKI Operations-$STAMP/" \
    "$PKI/root-ca/openssl.cnf"

###############################################################################
# 2. Generate Root CA self-signed certificate
###############################################################################

openssl req -config "$PKI/root-ca/openssl.cnf" \
    -key "$PKI/root-ca/private/root-ca.key" \
    -new -x509 -days 3650 \
    -extensions v3_ca \
    -out "$PKI/root-ca/certs/root-ca.crt"

chmod 444 "$PKI/root-ca/certs/root-ca.crt"

###############################################################################
# 3. Fix Intermediate CA openssl.cnf — three structural errors + OU stamp
###############################################################################

# Error 1: wrong dir path
sed -i 's|dir               = /wrong/path/intermediate-ca|dir               = /app/pki/intermediate-ca|' \
    "$PKI/intermediate-ca/openssl.cnf"

# Error 2: server_cert EKU emailProtection → serverAuth
sed -i 's/extendedKeyUsage = emailProtection/extendedKeyUsage = serverAuth/' \
    "$PKI/intermediate-ca/openssl.cnf"

# Error 3: missing crlnumber directive in CA_default
sed -i '/^crl_extensions    = crl_ext$/a\crlnumber         = $dir/crlnumber' \
    "$PKI/intermediate-ca/openssl.cnf"

# DNA: Append audit stamp to OU in req_distinguished_name
sed -i "s/organizationalUnitName          = Infrastructure/organizationalUnitName          = Infrastructure-$STAMP/" \
    "$PKI/intermediate-ca/openssl.cnf"

###############################################################################
# 4. Build Intermediate CA
###############################################################################

# Generate EC P-384 key
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:secp384r1 \
    -out "$PKI/intermediate-ca/private/intermediate-ca.key"
chmod 400 "$PKI/intermediate-ca/private/intermediate-ca.key"

# Create CSR with stamped OU
openssl req -config "$PKI/intermediate-ca/openssl.cnf" \
    -new -sha384 \
    -key "$PKI/intermediate-ca/private/intermediate-ca.key" \
    -out "$PKI/intermediate-ca/csr/intermediate-ca.csr" \
    -subj "/C=US/ST=California/L=San Francisco/O=SecureCorp/OU=Infrastructure-$STAMP/CN=SecureCorp Intermediate CA"

# Sign with Root CA
openssl ca -config "$PKI/root-ca/openssl.cnf" \
    -extensions v3_intermediate_ca \
    -days 1825 \
    -notext \
    -batch \
    -in "$PKI/intermediate-ca/csr/intermediate-ca.csr" \
    -out "$PKI/intermediate-ca/certs/intermediate-ca.crt"

chmod 444 "$PKI/intermediate-ca/certs/intermediate-ca.crt"

# Build chain file (intermediate first, then root)
cat "$PKI/intermediate-ca/certs/intermediate-ca.crt" \
    "$PKI/root-ca/certs/root-ca.crt" \
    > "$PKI/intermediate-ca/certs/ca-chain.crt"
chmod 444 "$PKI/intermediate-ca/certs/ca-chain.crt"

###############################################################################
# 5. Issue server certificate with deployment-specific SANs
###############################################################################

mkdir -p "$PKI/intermediate-ca/private/server" \
         "$PKI/intermediate-ca/certs/server"

openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:secp384r1 \
    -out "$PKI/intermediate-ca/private/server/web.securecorp.lab.key"
chmod 400 "$PKI/intermediate-ca/private/server/web.securecorp.lab.key"

openssl req -new -sha384 \
    -key "$PKI/intermediate-ca/private/server/web.securecorp.lab.key" \
    -out "$PKI/intermediate-ca/csr/web.securecorp.lab.csr" \
    -subj "/C=US/ST=California/O=SecureCorp/OU=WebOps-$STAMP/CN=web.securecorp.lab" \
    -addext "subjectAltName = DNS:web.securecorp.lab,DNS:www.securecorp.lab,IP:$SERVER_IP"

openssl ca -config "$PKI/intermediate-ca/openssl.cnf" \
    -extensions server_cert \
    -days 730 \
    -notext \
    -batch \
    -in "$PKI/intermediate-ca/csr/web.securecorp.lab.csr" \
    -out "$PKI/intermediate-ca/certs/server/web.securecorp.lab.crt"

chmod 444 "$PKI/intermediate-ca/certs/server/web.securecorp.lab.crt"

###############################################################################
# 6. Issue client certificate with stamped OU
###############################################################################

mkdir -p "$PKI/intermediate-ca/private/client" \
         "$PKI/intermediate-ca/certs/client"

openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:secp384r1 \
    -out "$PKI/intermediate-ca/private/client/alice.key"
chmod 400 "$PKI/intermediate-ca/private/client/alice.key"

openssl req -new -sha384 \
    -key "$PKI/intermediate-ca/private/client/alice.key" \
    -out "$PKI/intermediate-ca/csr/alice.csr" \
    -subj "/C=US/ST=California/O=SecureCorp/OU=Engineering-$STAMP/CN=Alice Chen/emailAddress=alice@securecorp.lab" \
    -addext "subjectAltName = email:alice@securecorp.lab"

openssl ca -config "$PKI/intermediate-ca/openssl.cnf" \
    -extensions usr_cert \
    -days 365 \
    -notext \
    -batch \
    -in "$PKI/intermediate-ca/csr/alice.csr" \
    -out "$PKI/intermediate-ca/certs/client/alice.crt"

chmod 444 "$PKI/intermediate-ca/certs/client/alice.crt"

###############################################################################
# 7. Revoke client certificate and generate CRL
###############################################################################

openssl ca -config "$PKI/intermediate-ca/openssl.cnf" \
    -revoke "$PKI/intermediate-ca/certs/client/alice.crt" \
    -crl_reason keyCompromise

openssl ca -config "$PKI/intermediate-ca/openssl.cnf" \
    -gencrl \
    -out "$PKI/intermediate-ca/crl/intermediate-ca.crl"

chmod 644 "$PKI/intermediate-ca/crl/intermediate-ca.crl"

###############################################################################
# 8. Verify
###############################################################################

echo "=== Verification ==="
openssl verify -CAfile "$PKI/root-ca/certs/root-ca.crt" \
    "$PKI/root-ca/certs/root-ca.crt"

openssl verify -CAfile "$PKI/root-ca/certs/root-ca.crt" \
    "$PKI/intermediate-ca/certs/intermediate-ca.crt"

openssl verify -CAfile "$PKI/intermediate-ca/certs/ca-chain.crt" \
    "$PKI/intermediate-ca/certs/server/web.securecorp.lab.crt"

echo "=== Done ==="
