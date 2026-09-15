#!/bin/bash

pip3 install cryptography==42.0.8 msgpack==1.0.8 -q

# 1. Generate PKI with OpenSSL (ECDSA P-256)
mkdir -p /app/pki

openssl ecparam -name prime256v1 -genkey -noout -out /app/pki/ca.key
openssl req -new -x509 -key /app/pki/ca.key -out /app/pki/ca.crt \
    -days 3650 -subj "/CN=tkdb-ca" -sha256

openssl ecparam -name prime256v1 -genkey -noout -out /app/pki/server.key
openssl req -new -key /app/pki/server.key -out /app/pki/server.csr \
    -subj "/CN=tkdb-server"
openssl x509 -req -in /app/pki/server.csr \
    -CA /app/pki/ca.crt -CAkey /app/pki/ca.key -CAcreateserial \
    -out /app/pki/server.crt -days 365 -sha256

# Verify PKI
openssl verify -CAfile /app/pki/ca.crt /app/pki/server.crt

# 2. Build database (derives keys from PKI, creates schema, populates orgs)
python3 /solution/build_db.py

# 3. Install service module
mkdir -p /app/tkdb
cp /solution/tkdb_service.py /app/tkdb/service.py

# 4. Write design evaluation
python3 /solution/write_evaluation.py
