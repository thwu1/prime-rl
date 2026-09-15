#!/usr/bin/env bash

# Step 1: Install the compiler backend
cp /solution/compiler.py /app/backend.py

# Step 2: Build the C simulator from source
gcc -O2 -o /app/tools/vsim /app/tools/vsim.c

# Step 3: Export all compiled programs to .vbin interchange format
mkdir -p /app/output
python3 /app/tools/vexport.py --all /app/output

# Step 4: Generate DOT dependency graphs and render SVGs with graphviz
for prog in smoke scheduling pressure mixed; do
    python3 /app/tools/vdot.py "/app/output/${prog}.vbin" > "/app/output/${prog}.dot"
    dot -Tsvg "/app/output/${prog}.dot" -o "/app/output/${prog}.svg"
done
