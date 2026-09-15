#!/bin/bash

set -e

# Copy solution into place
cp /solution/smiles_engine.py /app/smiles_analyze.py
chmod +x /app/smiles_analyze.py

echo "Solution installed at /app/smiles_analyze.py"
