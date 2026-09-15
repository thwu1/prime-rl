#!/bin/bash

set -e

# Generate the English Draughts RBG game description
python3 /solution/generate_draughts.py

cd /app

# Compile the RBG description to C++ using rbg2cpp
/app/rbg/rbg2cpp/bin/rbg2cpp -o reasoner draughts.rbg
echo "RBG compilation successful"

# Build the C++ perft test binary
g++ -std=c++23 -O2 reasoner.cpp /app/rbg/rbg2cpp/test/perft.cpp -I. -o perft_test
echo "C++ compilation successful"

# Verify perft counts at depths 1 through 7
echo ""
echo "=== Verifying perft counts ==="

EXPECTED_1=7
EXPECTED_2=49
EXPECTED_3=302
EXPECTED_4=1469
EXPECTED_5=7361
EXPECTED_6=36768
EXPECTED_7=179740

for depth in 1 2 3 4 5 6 7; do
    echo ""
    echo "--- Depth $depth ---"
    OUTPUT=$(./perft_test "$depth")
    echo "$OUTPUT"

    PERFT_VAL=$(echo "$OUTPUT" | grep "^perft:" | awk '{print $2}')
    EXPECTED_VAR="EXPECTED_${depth}"
    EXPECTED="${!EXPECTED_VAR}"

    if [ "$PERFT_VAL" != "$EXPECTED" ]; then
        echo "FAIL: depth $depth got $PERFT_VAL, expected $EXPECTED"
        exit 1
    fi
    echo "OK: depth $depth = $PERFT_VAL"
done

echo ""
echo "All perft counts verified successfully."
