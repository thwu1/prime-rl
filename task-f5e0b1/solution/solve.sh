#!/bin/bash

pip3 install cryptography==44.0.0 argon2-cffi==23.1.0 -q

# Deploy the hardened auth module first (solver imports it for migration)
cp /solution/hardened_auth.py /app/hardened_auth.py

python3 /solution/solver.py
