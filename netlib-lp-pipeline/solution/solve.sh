#!/bin/bash

set -e

# Install solver dependencies
pip3 install scipy==1.14.1 numpy==2.1.3 -q

# Compile the Netlib emps decompressor with gets() compatibility
cd /app/data
cp /solution/gets_compat.c .

gcc -o emps emps.c gets_compat.c -lm -std=gnu89 \
    -Wno-implicit-function-declaration -Wno-implicit-int 2>/dev/null || \
gcc -o emps emps.c gets_compat.c -lm -std=c89 \
    -Wno-implicit-function-declaration -Wno-implicit-int 2>/dev/null || \
gcc -o emps emps.c gets_compat.c -lm

# Decompress all 8 problems from Netlib compressed MPS to standard MPS
PROBLEMS="afiro sc50a adlittle share2b kb2 bore3d boeing2 capri"
for prob in $PROBLEMS; do
    ./emps < "${prob}.cmp" > "${prob}.mps"
done

# Solve all problems, construct duals, verify duality and CS
python3 /solution/solve_lps.py
