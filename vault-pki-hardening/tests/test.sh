#!/bin/bash

pip3 install pytest==8.3.4 -q

export VAULT_ADDR='http://127.0.0.1:8200'
export VAULT_TOKEN=$(cat /app/vault-creds/root-token 2>/dev/null || echo "")

# Start Vault if not running
if ! vault status -format=json > /dev/null 2>&1; then
    vault server -config=/app/vault-config.hcl > /tmp/vault-test.log 2>&1 &
    sleep 5
fi

# Unseal if sealed
SEALED=$(vault status -format=json 2>/dev/null | jq -r '.sealed' 2>/dev/null || echo "true")
if [ "$SEALED" = "true" ]; then
    vault operator unseal $(cat /app/vault-creds/unseal-key-1) > /dev/null 2>&1 || true
    vault operator unseal $(cat /app/vault-creds/unseal-key-2) > /dev/null 2>&1 || true
    sleep 2
fi

cd /tests
RESULT=$(pytest test_state.py -v 2>&1)
EXIT_CODE=$?

echo "$RESULT"

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
