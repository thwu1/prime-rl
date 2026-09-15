#!/bin/bash
#
# Solution: Fix build, fix 4 bugs, implement dedup hash table
#
# 1. CMakeLists.txt: add missing src/sdf_parser.c to source list
# 2. inchikey.c: fix triplet lookup table loop variable mapping
# 3. inchikey.c: fix byte endianness in encode_base26
# 4. inchikey.c: fix standard InChI prefix detection
# 5. sdf_parser.c: strip newline from InChI value read from SDF
# 6. dedup.c: implement hash table insert with linear probing

set -e
cd /app

# Apply all code fixes
python3 /solution/fix_all.py

# Build with CMake
mkdir -p build
cd build
cmake ..
make

# Verify
echo "=== --keys verification ==="
./inchi_pipeline --keys < /app/data/inchi_list.txt

echo ""
echo "=== --sdf verification ==="
./inchi_pipeline --sdf /app/data/molecules.sdf

echo ""
echo "=== --dedup verification ==="
./inchi_pipeline --dedup /app/data/molecules.sdf
