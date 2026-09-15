#!/bin/bash

set -e

# Copy the correct RBG implementation to /app
cp /solution/crown.rbg /app/crown.rbg

echo "=== Verifying RBG compilation ==="
RBG2CPP="/opt/rbg/rbg2cpp/bin/rbg2cpp"
WORKDIR=$(mktemp -d)

# Use cd into WORKDIR and -o reasoner (relative path) because rbg2cpp
# derives C++ namespace/header-guard names from the -o path.
# An absolute path like /tmp/xxx/reasoner produces invalid C++ identifiers.
(cd "$WORKDIR" && $RBG2CPP -Whide -o reasoner /app/crown.rbg)
echo "RBG compilation successful."

echo "=== Compiling C++ reasoner ==="
cp /opt/rbg/rbg2cpp/test/perft.cpp "$WORKDIR/"
(cd "$WORKDIR" && g++ -O3 -std=c++23 -c -o reasoner.o reasoner.cpp)
(cd "$WORKDIR" && g++ -O3 -std=c++23 -o perft_test reasoner.o perft.cpp)
echo "C++ compilation successful."

echo "=== Running perft at depths 1-4 ==="
for depth in 1 2 3 4; do
    echo "--- Depth $depth ---"
    "$WORKDIR/perft_test" "$depth"
    echo ""
done

echo "=== Cross-validating with Python reference ==="
python3 /tests/reference_game.py

rm -rf "$WORKDIR"

echo "=== Solution verified successfully ==="
