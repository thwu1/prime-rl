#!/bin/bash
# Initializes the Transit secrets engine to its current (pre-audit) state.
# This represents the production configuration as-deployed before the
# compliance audit was conducted.

set -e

export BAO_ADDR="http://127.0.0.1:8200"
export BAO_TOKEN="test-root-token"
export BAO_DISABLE_MLOCK=true

# Stop any running instance
pkill -f "bao server" 2>/dev/null || true
sleep 2

# Start OpenBao in dev mode
bao server -dev \
    -dev-root-token-id="$BAO_TOKEN" \
    -dev-listen-address="127.0.0.1:8200" \
    > /tmp/bao.log 2>&1 &

# Wait for server readiness
for i in $(seq 1 30); do
    if curl -s "$BAO_ADDR/v1/sys/health" > /dev/null 2>&1; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: OpenBao failed to start"
        exit 1
    fi
    sleep 1
done

# Mount transit secrets engine
bao secrets enable transit 2>/dev/null || true

# Create encryption key (deployed without exportable flag)
bao write transit/keys/primary-enc type=aes256-gcm96 > /dev/null

# Create signing key
bao write transit/keys/tenant-sign type=ecdsa-p256 > /dev/null

echo "Transit engine initialized — pre-audit state ready."
