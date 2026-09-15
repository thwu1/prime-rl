#!/bin/bash

set -euo pipefail

echo "=== Step 1: Build liboqs with correct minimal configuration ==="
cd /app/liboqs-src

# FIX: Use CMake build identifiers (KEM_ml_kem_512) not display names (ML-KEM-512)
# FIX: Add -DBUILD_SHARED_LIBS=ON (Python wrapper needs .so, default is OFF/static)
cmake -S . -B build \
    -GNinja \
    -DCMAKE_INSTALL_PREFIX=/opt/liboqs \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=ON \
    -DOQS_BUILD_ONLY_LIB=ON \
    -DOQS_MINIMAL_BUILD="KEM_ml_kem_512;KEM_ml_kem_768;KEM_ml_kem_1024;SIG_ml_dsa_44;SIG_ml_dsa_65;SIG_ml_dsa_87" \
    -DOQS_USE_OPENSSL=ON

cmake --build build -- -j"$(nproc)"
cmake --install build

echo "=== Step 2: Configure shared library paths ==="
export LD_LIBRARY_PATH="/opt/liboqs/lib:${LD_LIBRARY_PATH:-}"
echo "/opt/liboqs/lib" > /etc/ld.so.conf.d/liboqs.conf 2>/dev/null || true
ldconfig 2>/dev/null || true

echo "=== Step 3: Compile fixed C audit program ==="
cd /app
cp /solution/pqc_audit.c /app/pqc_audit_fixed.c

# FIX: Use correct include/lib paths pointing to /opt/liboqs
# FIX: Add -Wl,-rpath for runtime library resolution
gcc -O2 \
    -I/opt/liboqs/include \
    -L/opt/liboqs/lib \
    -Wl,-rpath,/opt/liboqs/lib \
    -o /app/pqc_audit \
    /app/pqc_audit_fixed.c \
    -loqs -lcrypto

echo "=== Step 4: Run C audit ==="
mkdir -p /app/output
/app/pqc_audit

echo "=== Step 5: Install and run Python verification ==="
# The 0.15.0 wheel was removed from the configured package index. The 0.16.0
# wrapper retains the enumeration API used below and can load this system liboqs.
pip3 install liboqs-python==0.16.0 -q

cp /solution/pqc_verify.py /app/pqc_verify.py
python3 /app/pqc_verify.py

echo "=== Step 6: Run cross-check ==="
cp /solution/cross_check.py /app/cross_check.py
python3 /app/cross_check.py

echo "=== All steps completed successfully ==="
