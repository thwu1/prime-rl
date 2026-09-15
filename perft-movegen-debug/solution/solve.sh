#!/bin/bash

pip3 install chess==1.11.2 -q

# Deploy the perft comparison tool
cp /solution/perft_compare.py /app/perft_compare.py

# Run the comparison tool on initial position to demonstrate discrepancies
echo "=== Before fix: comparing engine vs Stockfish ==="
python3 /app/perft_compare.py "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1" 2 || true

# Apply all four bug fixes
python3 /solution/fix_engine.py

# Verify with comparison tool
echo ""
echo "=== After fix: comparing engine vs Stockfish ==="
python3 /app/perft_compare.py "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1" 3

echo ""
echo "=== Position 3 check ==="
python3 /app/perft_compare.py "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1" 3
