#!/bin/bash

export BAO_ADDR="http://127.0.0.1:8200"

# Ensure OpenBao is running and unsealed
if [ -f /app/state/init.json ]; then
    HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "$BAO_ADDR/v1/sys/health" 2>/dev/null || echo "000")
    if [ "$HEALTH" = "000" ]; then
        nohup bao server -config=/app/bao-config.hcl > /tmp/bao-test.log 2>&1 &
        sleep 3
    fi

    SEALED=$(curl -s "$BAO_ADDR/v1/sys/health" 2>/dev/null | jq -r '.sealed // false')
    if [ "$SEALED" = "true" ]; then
        UNSEAL_KEY=$(jq -r '.unseal_keys_b64[0]' /app/state/init.json)
        curl -s -X PUT "$BAO_ADDR/v1/sys/unseal" -d "{\"key\": \"$UNSEAL_KEY\"}" > /dev/null
        sleep 1
    fi
fi

RESULT=$(pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?
echo "$RESULT"

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
