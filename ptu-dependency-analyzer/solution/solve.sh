#!/usr/bin/env bash

set -e

# Install solution dependencies
pip3 install tree-sitter==0.22.3 tree-sitter-cpp==0.22.3 -q

# Deploy solution
cp /solution/ptu_analyzer.py /app/ptu_analyzer.py
chmod +x /app/ptu_analyzer.py

# Verify it runs on all three sessions
python3 /app/ptu_analyzer.py /app/sessions/session_alpha.txt deps 0
python3 /app/ptu_analyzer.py /app/sessions/session_beta.txt deps 0
python3 /app/ptu_analyzer.py /app/sessions/session_gamma.txt deps 0
