#!/bin/bash

set -e

# Apply all fixes and create ABI architecture
python3 /solution/fix_bugs.py

# Build from scratch to verify
cd /app
rm -rf build
mkdir build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=/usr \
         -DCMAKE_C_FLAGS="-Werror=implicit-function-declaration"
make -j"$(nproc)"
make install DESTDIR=/tmp/solve_verify

echo "All defects fixed and ABI architecture created. Build and install successful."
