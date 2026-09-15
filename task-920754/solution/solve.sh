#!/usr/bin/env bash

set -e

# Install dependencies
pip3 install PyJWT==2.9.0 pyotp==2.9.0 -q

# ============================================================
# 1. Create PKI infrastructure
# ============================================================
mkdir -p /app/pki
cd /app/pki

# Generate CA key and self-signed certificate
openssl req -x509 -newkey rsa:2048 -keyout ca.key -out ca.pem \
    -days 365 -nodes -subj "/CN=ESV Test CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"

# Generate server key and CSR with SAN
openssl req -newkey rsa:2048 -keyout server.key -out server.csr \
    -nodes -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

# Sign server cert with CA (copy SAN from CSR)
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key \
    -CAcreateserial -out server.pem -days 365 \
    -copy_extensions copy

# Generate client key and CSR
openssl req -newkey rsa:2048 -keyout client.key -out client.csr \
    -nodes -subj "/CN=ESVTestClient"

# Sign client cert with CA
openssl x509 -req -in client.csr -CA ca.pem -CAkey ca.key \
    -CAcreateserial -out client.pem -days 365

# Clean up CSRs
rm -f server.csr client.csr ca.srl

# ============================================================
# 2. Deploy server code
# ============================================================
mkdir -p /app/esv_server
cp /solution/server.py /app/esv_server/server.py
cp /solution/validator.py /app/esv_server/validator.py

# ============================================================
# 3. Start server in background
# ============================================================
cd /app
nohup python3 /app/esv_server/server.py > /tmp/esv_server.log 2>&1 &
sleep 2

echo "ESV server deployed and running on port 8443"
