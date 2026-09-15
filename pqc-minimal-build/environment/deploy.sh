#!/bin/bash
set -euo pipefail

echo "=== Building liboqs from source ==="
cd /app/liboqs-src

cmake -S . -B build \
    -GNinja \
    -DCMAKE_INSTALL_PREFIX=/opt/liboqs \
    -DCMAKE_BUILD_TYPE=Release \
    -DOQS_BUILD_ONLY_LIB=ON \
    -DOQS_MINIMAL_BUILD="ML-KEM-512;ML-KEM-768;ML-KEM-1024;ML-DSA-44;ML-DSA-65;ML-DSA-87" \
    -DOQS_USE_OPENSSL=ON

cmake --build build -- -j$(nproc)
cmake --install build

echo "=== Compiling PQC audit tool ==="
cd /app
gcc -O2 -I/usr/local/include -L/usr/local/lib \
    -o /app/pqc_audit /app/pqc-migration/pqc_audit.c -loqs -lcrypto

mkdir -p /app/output

echo "=== Running PQC audit ==="
/app/pqc_audit

echo "=== Running Python integration test ==="
pip3 install liboqs-python
python3 /app/pqc-migration/verify_migration.py

echo "=== Deployment complete ==="
