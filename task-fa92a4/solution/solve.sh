#!/bin/bash

# Stop any existing named instance
pkill named 2>/dev/null || true
sleep 1

# Apply all security configurations via Python helper
python3 /solution/secure_dns.py
if [ $? -ne 0 ]; then
    echo "ERROR: Configuration generation failed" >&2
    exit 1
fi

# Start named as daemon
named -u bind -c /etc/bind/named.conf
sleep 2

# Verify named started
if ! pgrep -x named >/dev/null; then
    echo "ERROR: named failed to start" >&2
    # Try foreground to see error
    named -u bind -c /etc/bind/named.conf -g 2>&1 | head -30 &
    sleep 3
    kill %1 2>/dev/null
    exit 1
fi

echo "named started successfully"

# Wait for DNSSEC signing to complete (up to 120 seconds)
echo "Waiting for DNSSEC signing to complete..."
for i in $(seq 1 40); do
    result=$(dig @127.0.0.1 weilburg.corp DNSKEY +short +timeout=3 2>/dev/null)
    if [ -n "$result" ]; then
        echo "DNSSEC signing complete"
        sleep 3
        break
    fi
    sleep 3
done

# Verification
echo ""
echo "=== Verification ==="
named-checkconf /etc/bind/named.conf && echo "named-checkconf: PASS"

echo ""
echo "--- A record ---"
dig @127.0.0.1 weilburg.corp A +short

echo ""
echo "--- DNSKEY ---"
dig @127.0.0.1 weilburg.corp DNSKEY +short | head -2

echo ""
echo "--- NSEC3PARAM ---"
dig @127.0.0.1 weilburg.corp NSEC3PARAM +short

echo ""
echo "--- RPZ test: malware.evil.test ---"
dig @127.0.0.1 malware.evil.test A +short

echo ""
echo "--- RPZ test: phishing.evil.test ---"
dig @127.0.0.1 phishing.evil.test A +short

echo ""
echo "=== Done ==="
