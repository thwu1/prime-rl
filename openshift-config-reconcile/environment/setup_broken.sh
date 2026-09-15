#!/bin/bash
set -e

# Generate broken htpasswd file with MD5 (-m) instead of bcrypt (-B)
# Also deliberately missing dev-beta and ops-viewer entries
htpasswd -c -m -b /app/broken/htpasswd cluster-admin-01 Kx9mP2vL7nQ4
htpasswd -m -b /app/broken/htpasswd team-lead Rf4wE8jY3bN5
htpasswd -m -b /app/broken/htpasswd dev-alpha Gm6tH1kU5cA2
htpasswd -m -b /app/broken/htpasswd qa-engineer Wq2bV4hL8mK6

# Generate broken TLS certificates
mkdir -p /app/broken/tls

# CA key and cert
openssl genrsa -out /app/broken/tls/ca.key 2048 2>/dev/null
openssl req -x509 -new -nodes -key /app/broken/tls/ca.key -sha256 -days 3650 \
    -out /app/broken/tls/ca.crt -subj "/CN=ACME Internal CA" 2>/dev/null

# Frontend cert with WRONG SAN (wrong-domain.com instead of acme.example.com)
openssl genrsa -out /app/broken/tls/frontend.key 2048 2>/dev/null

printf 'subjectAltName = DNS:www.wrong-domain.com,DNS:wrong-domain.com\n' > /tmp/wrong_san_ext.cnf

openssl req -new -key /app/broken/tls/frontend.key \
    -out /tmp/frontend.csr -subj "/CN=www.acme.example.com" 2>/dev/null

openssl x509 -req -in /tmp/frontend.csr \
    -CA /app/broken/tls/ca.crt -CAkey /app/broken/tls/ca.key -CAcreateserial \
    -out /app/broken/tls/frontend.crt -days 365 -sha256 \
    -extfile /tmp/wrong_san_ext.cnf 2>/dev/null

rm -f /tmp/frontend.csr /tmp/wrong_san_ext.cnf /app/broken/tls/ca.srl
