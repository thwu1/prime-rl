#!/bin/bash

pip3 install cryptography==44.0.0 -q

cd /app
python3 /solution/solve_audit.py
