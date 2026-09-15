#!/bin/bash

set -e

cd /app

# ============================================================
# Step 1: Fix scanner.l — add %option noyywrap
# ============================================================
python3 /solution/fix_sources.py

# ============================================================
# Step 2: Build the parser
# ============================================================
make clean || true
make

# ============================================================
# Step 3: Install the optimizer and dot_output solutions
# ============================================================
cp /solution/optimizer_solution.py /app/optimizer.py
cp /solution/dot_output_solution.py /app/dot_output.py

# ============================================================
# Step 4: Verify the pipeline works
# ============================================================
echo "=== Testing parser ==="
echo 'func main() { print 42; }' | ./decaf2tac | python3 main.py

echo "=== Testing with sample programs ==="
./decaf2tac < sample_programs/simple.dcf | python3 main.py
./decaf2tac < sample_programs/precedence.dcf | python3 main.py
./decaf2tac < sample_programs/control.dcf | python3 main.py --dot /tmp/dots

echo "=== Verifying DOT output ==="
dot -Tsvg /tmp/dots/main.dot > /dev/null
echo "Pipeline verified successfully."
