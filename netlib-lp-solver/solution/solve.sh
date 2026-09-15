#!/bin/bash

pip3 install numpy==1.26.4 -q

cd /app

# Step 1: Compile the emps decompressor
echo "Compiling emps.c..."
gcc -w -o /app/emps /app/emps.c -lm
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to compile emps.c"
    exit 1
fi

# Step 2: Decompress all MPS benchmark files
echo "Decompressing benchmark files..."
mkdir -p /app/problems
for prob in afiro sc50b kb2 share2b adlittle; do
    /app/emps < /app/compressed/$prob > /app/problems/${prob}.mps
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to decompress $prob"
        exit 1
    fi
    echo "  Decompressed: $prob ($(wc -l < /app/problems/${prob}.mps) lines)"
done

# Step 3: Copy solver to /app/ and run it
cp /solution/solver.py /app/solver.py
echo "Running LP solver..."
python3 /app/solver.py
