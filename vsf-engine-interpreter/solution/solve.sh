#!/bin/bash

set -e

pip3 install flask==3.1.0 -q

# Generate PKI hierarchy
bash /solution/pki_setup.sh

# Deploy application files
cp /solution/esvts_auth.py /app/esvts_auth.py
cp /solution/vsf_engine.py /app/vsf_engine.py
cp /solution/esvts_server.py /app/esvts_server.py
cp /solution/esvts_client.py /app/esvts_client.py

echo "Solution deployed."
