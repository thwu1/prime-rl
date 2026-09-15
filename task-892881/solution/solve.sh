#!/bin/bash

# Copy solution files to /app
cp /solution/gdl_engine.py /app/gdl_engine.py
cp /solution/gdl_prover.pl /app/gdl_prover.pl
chmod +x /app/gdl_engine.py

# Verify basic functionality across all three games
echo "=== Verifying switches.kif ==="
python3 /app/gdl_engine.py /app/games/switches.kif roles
python3 /app/gdl_engine.py /app/games/switches.kif initial

echo "=== Verifying tictactoe.kif ==="
python3 /app/gdl_engine.py /app/games/tictactoe.kif roles
python3 /app/gdl_engine.py /app/games/tictactoe.kif initial

echo "=== Verifying connectfour.kif ==="
python3 /app/gdl_engine.py /app/games/connectfour.kif roles
python3 /app/gdl_engine.py /app/games/connectfour.kif initial

echo "=== Solution deployed successfully ==="
