#!/bin/bash

set -e

# Build liboqs from source with minimal algorithm set
cd /app/liboqs
cmake -S . -B build -GNinja \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DBUILD_SHARED_LIBS=ON \
    -DOQS_MINIMAL_BUILD="KEM_ml_kem_512;KEM_ml_kem_768;KEM_ml_kem_1024;SIG_ml_dsa_44;SIG_ml_dsa_65;SIG_ml_dsa_87" \
    -DOQS_BUILD_ONLY_LIB=ON \
    -DCMAKE_BUILD_TYPE=Release
ninja -C build
ninja -C build install
ldconfig

# Install the fixed and new source files
cp /solution/fixed_kem.c /app/broken_kem.c
cp /solution/hybrid_kem.c /app/hybrid_kem.c
cp /solution/sig_matrix.c /app/sig_matrix.c
cp /solution/Makefile /app/Makefile

# Build all programs
cd /app
make

# Run all programs
mkdir -p /app/output
./broken_kem
./hybrid_kem
./sig_matrix
