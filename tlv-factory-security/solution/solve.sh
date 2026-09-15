#!/usr/bin/env bash

export PIP_BREAK_SYSTEM_PACKAGES=1

python3 -m pip install cryptography==44.0.3 pyyaml==6.0.2 -q 2>&1

# Ensure test keys exist (fallback if Dockerfile key generation was skipped)
if [ ! -f /app/test_keys/private.pem ]; then
    mkdir -p /app/test_keys
    openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:prime256v1 -out /app/test_keys/private.pem 2>/dev/null
    openssl pkey -in /app/test_keys/private.pem -pubout -out /app/test_keys/public.pem 2>/dev/null
fi

cp /solution/tlv_manager.py /app/tlv_manager.py
chmod +x /app/tlv_manager.py
