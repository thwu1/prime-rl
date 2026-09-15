#!/bin/bash
# Perft runner wrapper - outputs divide-format results
# Usage: ./perft.sh <depth> "<fen>" [moves]
python3 /app/chess_engine.py "$@"
