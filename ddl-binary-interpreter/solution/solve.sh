#!/bin/bash

cd /app

# Copy the transpiler into place
cp /solution/ddl_transpile.py /app/ddl_transpile.py

# Transpile all format specs to C
mkdir -p /app/generated
for fmt in container tagged choice chunk_stream; do
    echo "=== Transpiling ${fmt}.ddl ==="
    python3 /app/ddl_transpile.py /app/formats/${fmt}.ddl /app/generated/${fmt}.c
done

# Compile all generated parsers using make
echo "=== Compiling via make ==="
make -f /app/Makefile.template all

# Test all parsers
echo "=== Testing container ==="
/app/generated/container /app/inputs/input_container.bin

echo "=== Testing tagged ==="
/app/generated/tagged /app/inputs/input_tagged.bin

echo "=== Testing choice ==="
/app/generated/choice /app/inputs/input_choice.bin

echo "=== Testing chunk_stream ==="
/app/generated/chunk_stream /app/inputs/input_chunk.bin

echo "=== Testing error case (should fail) ==="
/app/generated/container /app/inputs/input_truncated.bin && echo "ERROR: should have failed" || echo "Correctly failed"

# Run valgrind validation and generate report
echo "=== Running valgrind validation ==="
make -f /app/Makefile.template validate

echo "Done."
