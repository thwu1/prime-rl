#!/bin/bash

set -euo pipefail

# Stop any running services
pkill -x nsd 2>/dev/null || true
pkill -x unbound 2>/dev/null || true
sleep 1

# Apply all configuration fixes
python3 /solution/fix_dns.py

# Validate unbound config before starting
unbound-checkconf /app/dns/unbound.conf

# Start NSD
nsd -c /app/dns/nsd.conf
sleep 2

# Verify NSD is responding
echo "=== NSD direct query ==="
dig @127.0.0.1 -p 5353 www.acme-internal.test A +short

# Start Unbound
unbound -c /app/dns/unbound.conf
sleep 3

# Wait for Unbound to be ready
echo "=== Waiting for Unbound ==="
READY=0
for i in $(seq 1 20); do
    RESULT=$(dig @127.0.0.1 -p 5300 www.acme-internal.test A +short +timeout=2 2>/dev/null || echo "")
    if echo "${RESULT}" | grep -q "203.0.113.10"; then
        echo "Unbound ready after ${i} attempts"
        READY=1
        break
    fi
    echo "Waiting... attempt ${i} (got: ${RESULT})"
    sleep 2
done

if [ "${READY}" -eq 0 ]; then
    echo "ERROR: Unbound did not become ready"
    cat /app/dns/unbound.log 2>/dev/null || true
    exit 1
fi

# Verify all aspects
echo "=== Verification ==="
echo "Forward lookup:"
dig @127.0.0.1 -p 5300 www.acme-internal.test A +short

echo "DNSSEC validation:"
dig @127.0.0.1 -p 5300 www.acme-internal.test A +dnssec +short

echo "Reverse lookup:"
dig @127.0.0.1 -p 5300 10.113.0.203.in-addr.arpa PTR +short

echo "Private address filtering (trap.evil.test - should be empty):"
dig @127.0.0.1 -p 5300 trap.evil.test A +short || true

echo "Non-private passthrough (legit.evil.test):"
dig @127.0.0.1 -p 5300 legit.evil.test A +short

echo "DNS infrastructure diagnosis and repair complete."
