#!/usr/bin/env bash


cd /app

# Deploy complete engine implementation
cp /solution/engine_complete.py /app/proof_engine/engine.py

# Deploy complete CLI validator with JSON, DOT, and obligations support
cp /solution/validate_proof_complete.py /app/validate_proof.py

echo "Solution deployed."
