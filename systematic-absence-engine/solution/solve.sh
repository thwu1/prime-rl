#!/bin/bash

pip3 install spglib==2.4.0 numpy==2.0.2 -q

# Deploy reference implementation
cp /solution/refcond_ref.py /app/refcond.py

# Verify deployment
echo "--- Smoke test ---"
python3 /app/refcond.py check 14 1 0 1
python3 /app/refcond.py check 14 1 0 2
python3 /app/refcond.py check 225 1 1 1
python3 /app/refcond.py check 225 1 0 0
echo "--- Derive smoke test ---"
python3 /app/refcond.py derive 14
echo "--- Transform smoke test ---"
echo "1 0 1" | python3 /app/refcond.py check-transformed 14 '[[0,1,0],[1,0,0],[0,0,1]]'
echo "--- Done ---"
