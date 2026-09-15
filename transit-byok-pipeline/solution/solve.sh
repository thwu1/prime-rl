#!/bin/bash

pip3 install cryptography==43.0.3 requests==2.32.3 -q

# Start OpenBao server with file storage
nohup bao server -config=/app/bao-config.hcl > /tmp/bao.log 2>&1 &
sleep 3

export BAO_ADDR="http://127.0.0.1:8200"

# Initialize with single key share
INIT_OUTPUT=$(bao operator init -key-shares=1 -key-threshold=1 -format=json)
echo "$INIT_OUTPUT" > /app/state/init.json

UNSEAL_KEY=$(echo "$INIT_OUTPUT" | jq -r '.unseal_keys_b64[0]')
ROOT_TOKEN=$(echo "$INIT_OUTPUT" | jq -r '.root_token')

# Unseal
bao operator unseal "$UNSEAL_KEY"
sleep 1

export BAO_TOKEN="$ROOT_TOKEN"

# Enable transit secrets engine
bao secrets enable transit

# Run the main pipeline
python3 /solution/pipeline.py "$ROOT_TOKEN"
