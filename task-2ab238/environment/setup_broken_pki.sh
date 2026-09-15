#!/bin/bash
# Generate a deliberately broken PKI environment for assessment

mkdir -p /app/pki

# ============================================================
# Root CA: WEAK 1024-bit RSA key, NO basicConstraints extension
# ============================================================
openssl genrsa 1024 2>/dev/null > /app/pki/root-ca.key

cat > /tmp/root_ext.cnf << 'ENDCNF'
[req]
distinguished_name = dn
prompt = no

[dn]
C = US
ST = California
O = AcmeCorp
CN = AcmeCorp Root CA

[v3_root]
subjectKeyIdentifier = hash
keyUsage = critical, keyCertSign, cRLSign
ENDCNF

openssl req -new -x509 -key /app/pki/root-ca.key -sha256 -days 3650 \
  -config /tmp/root_ext.cnf -extensions v3_root \
  -out /app/pki/root-ca.pem

# ============================================================
# Intermediate CA: SHA-1 signature (deprecated), pathlen:0
# ============================================================
openssl genrsa 2048 2>/dev/null > /app/pki/intermediate-ca.key

openssl req -new -key /app/pki/intermediate-ca.key \
  -subj "/C=US/ST=California/O=AcmeCorp/CN=AcmeCorp Intermediate CA" \
  -out /tmp/intermediate.csr

cat > /tmp/intermediate_ext.cnf << 'ENDCNF'
[v3_intermediate]
basicConstraints = critical, CA:TRUE, pathlen:0
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
keyUsage = critical, keyCertSign, cRLSign
ENDCNF

openssl x509 -req -in /tmp/intermediate.csr \
  -CA /app/pki/root-ca.pem -CAkey /app/pki/root-ca.key \
  -CAcreateserial -sha1 -days 1825 \
  -extfile /tmp/intermediate_ext.cnf -extensions v3_intermediate \
  -out /app/pki/intermediate-ca.pem

# ============================================================
# Sub-CA: signed by pathlen:0 intermediate — VIOLATION of RFC 5280
# ============================================================
openssl genrsa 2048 2>/dev/null > /app/pki/sub-ca.key

openssl req -new -key /app/pki/sub-ca.key \
  -subj "/C=US/ST=California/O=AcmeCorp/CN=AcmeCorp Sub CA" \
  -out /tmp/sub_ca.csr

cat > /tmp/sub_ca_ext.cnf << 'ENDCNF'
[v3_sub_ca]
basicConstraints = critical, CA:TRUE
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
keyUsage = critical, keyCertSign, cRLSign
ENDCNF

openssl x509 -req -in /tmp/sub_ca.csr \
  -CA /app/pki/intermediate-ca.pem -CAkey /app/pki/intermediate-ca.key \
  -CAcreateserial -sha256 -days 730 \
  -extfile /tmp/sub_ca_ext.cnf -extensions v3_sub_ca \
  -out /app/pki/sub-ca.pem

# ============================================================
# Server cert: CA:TRUE (wrong), no SAN, keyCertSign in keyUsage
# ============================================================
openssl genrsa 2048 2>/dev/null > /app/pki/server.key

openssl req -new -key /app/pki/server.key \
  -subj "/C=US/ST=California/O=AcmeCorp/CN=server.acmecorp.internal" \
  -out /tmp/server.csr

cat > /tmp/server_ext.cnf << 'ENDCNF'
[v3_server]
basicConstraints = CA:TRUE
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
keyUsage = critical, digitalSignature, keyEncipherment, keyCertSign
extendedKeyUsage = serverAuth
ENDCNF

openssl x509 -req -in /tmp/server.csr \
  -CA /app/pki/intermediate-ca.pem -CAkey /app/pki/intermediate-ca.key \
  -CAcreateserial -sha256 -days 365 \
  -extfile /tmp/server_ext.cnf -extensions v3_server \
  -out /app/pki/server.pem

# ============================================================
# Client cert: wrong EKU (serverAuth), KEY REUSE with server
# ============================================================
cat /app/pki/server.key > /app/pki/client.key

openssl req -new -key /app/pki/client.key \
  -subj "/C=US/ST=California/O=AcmeCorp/CN=client.acmecorp.internal" \
  -out /tmp/client.csr

cat > /tmp/client_ext.cnf << 'ENDCNF'
[v3_client]
basicConstraints = critical, CA:FALSE
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth
ENDCNF

openssl x509 -req -in /tmp/client.csr \
  -CA /app/pki/intermediate-ca.pem -CAkey /app/pki/intermediate-ca.key \
  -CAcreateserial -sha256 -days 365 \
  -extfile /tmp/client_ext.cnf -extensions v3_client \
  -out /app/pki/client.pem

# ============================================================
# DH params: pre-generated weak 1024-bit (vulnerable to Logjam)
# Already COPY'd into /app/pki/dhparams.pem by Dockerfile
# ============================================================

# ============================================================
# Insecure nginx TLS configuration
# ============================================================
cat > /app/pki/nginx-tls.conf << 'ENDCNF'
server {
    listen 443 ssl;
    server_name server.acmecorp.internal;

    ssl_certificate /etc/nginx/ssl/server.pem;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    ssl_protocols SSLv3 TLSv1 TLSv1.1 TLSv1.2;
    ssl_ciphers ALL:!aNULL;
    ssl_prefer_server_ciphers off;
    ssl_dhparam /etc/nginx/ssl/dhparams.pem;

    location / {
        proxy_pass http://backend:8080;
    }
}
ENDCNF

# Clean up temp files
rm -f /tmp/*.cnf /tmp/*.csr

# Verify all required files exist
echo "=== Verifying broken PKI files ==="
FAIL=0
for f in root-ca.key root-ca.pem intermediate-ca.key intermediate-ca.pem \
         sub-ca.key sub-ca.pem server.key server.pem client.key client.pem \
         dhparams.pem nginx-tls.conf; do
    if [ ! -s "/app/pki/$f" ]; then
        echo "ERROR: /app/pki/$f missing or empty!" >&2
        FAIL=1
    else
        echo "  OK: $f ($(wc -c < /app/pki/$f) bytes)"
    fi
done

# Verify key reuse is in place
if ! diff -q /app/pki/server.key /app/pki/client.key > /dev/null 2>&1; then
    echo "ERROR: server.key and client.key should be identical!" >&2
    FAIL=1
else
    echo "  OK: server.key == client.key (key reuse verified)"
fi

# Verify intermediate has pathlen:0
if ! openssl x509 -in /app/pki/intermediate-ca.pem -text -noout 2>/dev/null | grep -q "pathlen:0"; then
    echo "ERROR: intermediate-ca.pem missing pathlen:0!" >&2
    FAIL=1
else
    echo "  OK: intermediate-ca.pem has pathlen:0"
fi

# Verify sub-ca has CA:TRUE
if ! openssl x509 -in /app/pki/sub-ca.pem -text -noout 2>/dev/null | grep -q "CA:TRUE"; then
    echo "ERROR: sub-ca.pem missing CA:TRUE!" >&2
    FAIL=1
else
    echo "  OK: sub-ca.pem has CA:TRUE (pathlen violation)"
fi

if [ "$FAIL" -eq 1 ]; then
    echo "FATAL: broken PKI verification failed!" >&2
    exit 1
fi

echo "Broken PKI environment created at /app/pki/"
ls -la /app/pki/
