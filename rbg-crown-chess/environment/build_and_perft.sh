#!/bin/bash
# Build an RBG game and run perft test
# Usage: ./build_and_perft.sh <game.rbg> [depth]
# Example: ./build_and_perft.sh crown.rbg 3

set -e

GAME="$1"
DEPTH="${2:-3}"
RBG2CPP="/opt/rbg/rbg2cpp/bin/rbg2cpp"
WORKDIR=$(mktemp -d)

if [ -z "$GAME" ]; then
    echo "Usage: $0 <game.rbg> [depth]"
    exit 1
fi

if [ ! -f "$GAME" ]; then
    echo "Error: File '$GAME' not found"
    exit 1
fi

# Convert to absolute path for use after cd
GAME_ABS=$(readlink -f "$GAME")

echo "=== Compiling RBG game: $GAME ==="
# Use cd into WORKDIR and -o reasoner (relative path) because rbg2cpp
# derives C++ namespace/header-guard names from the -o path.
# An absolute path produces invalid C++ identifiers containing '/'.
(cd "$WORKDIR" && $RBG2CPP -Whide -o reasoner "$GAME_ABS")
echo "RBG compilation successful."

echo "=== Compiling C++ reasoner ==="
cp /opt/rbg/rbg2cpp/test/perft.cpp "$WORKDIR/"
(cd "$WORKDIR" && g++ -O3 -std=c++23 -c -o reasoner.o reasoner.cpp)
(cd "$WORKDIR" && g++ -O3 -std=c++23 -o perft_test reasoner.o perft.cpp)
echo "C++ compilation successful."

echo "=== Running perft at depth $DEPTH ==="
"$WORKDIR/perft_test" "$DEPTH"

rm -rf "$WORKDIR"
