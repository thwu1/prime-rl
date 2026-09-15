#!/bin/bash
#
# Generate PKI hierarchy for ESVTS mTLS
#

set -e

PKI_DIR="/app/pki"
mkdir -p "$PKI_DIR"

# 1. Root CA
openssl genrsa -out "$PKI_DIR/ca.key" 2048 2>/dev/null
openssl req -x509 -new -nodes \
    -key "$PKI_DIR/ca.key" \
    -sha256 -days 3650 \
    -subj "/C=US/O=NIST ESVTS Mock/CN=ESVTS Root CA" \
    -out "$PKI_DIR/ca.crt" 2>/dev/null

# 2. Server certificate with SAN
cat > "$PKI_DIR/server_ext.cnf" <<EXTEOF
[req]
distinguished_name = req_dn
req_extensions = v3_req
prompt = no

[req_dn]
CN = localhost

[v3_req]
subjectAltName = DNS:localhost,IP:127.0.0.1
extendedKeyUsage = serverAuth
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
EXTEOF

openssl genrsa -out "$PKI_DIR/server.key" 2048 2>/dev/null
openssl req -new -nodes \
    -key "$PKI_DIR/server.key" \
    -subj "/CN=localhost" \
    -config "$PKI_DIR/server_ext.cnf" \
    -out "$PKI_DIR/server.csr" 2>/dev/null

openssl x509 -req \
    -in "$PKI_DIR/server.csr" \
    -CA "$PKI_DIR/ca.crt" \
    -CAkey "$PKI_DIR/ca.key" \
    -CAcreateserial \
    -days 365 \
    -sha256 \
    -extfile "$PKI_DIR/server_ext.cnf" \
    -extensions v3_req \
    -out "$PKI_DIR/server.crt" 2>/dev/null

# 3. Client certificate
cat > "$PKI_DIR/client_ext.cnf" <<EXTEOF
[req]
distinguished_name = req_dn
req_extensions = v3_req
prompt = no

[req_dn]
CN = ESVTS Client

[v3_req]
extendedKeyUsage = clientAuth
basicConstraints = CA:FALSE
keyUsage = digitalSignature
EXTEOF

openssl genrsa -out "$PKI_DIR/client.key" 2048 2>/dev/null
openssl req -new -nodes \
    -key "$PKI_DIR/client.key" \
    -subj "/CN=ESVTS Client" \
    -config "$PKI_DIR/client_ext.cnf" \
    -out "$PKI_DIR/client.csr" 2>/dev/null

openssl x509 -req \
    -in "$PKI_DIR/client.csr" \
    -CA "$PKI_DIR/ca.crt" \
    -CAkey "$PKI_DIR/ca.key" \
    -CAcreateserial \
    -days 365 \
    -sha256 \
    -extfile "$PKI_DIR/client_ext.cnf" \
    -extensions v3_req \
    -out "$PKI_DIR/client.crt" 2>/dev/null

# Cleanup CSRs and serial files
rm -f "$PKI_DIR"/*.csr "$PKI_DIR"/*.srl "$PKI_DIR"/*.cnf

echo "PKI hierarchy generated at $PKI_DIR"
