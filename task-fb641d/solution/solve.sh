#!/usr/bin/env bash

set -e

# Deploy the corrected DNS server implementation
cp /solution/dns_server.py /app/dns_server.py
chmod +x /app/dns_server.py

# Generate the compliance report documenting discovered RFC violations
python3 /solution/write_report.py

# Start the fixed server for verification
python3 /app/dns_server.py --zone /app/zones/example.com.zone --port 1053 &
SERVER_PID=$!
sleep 2

# Smoke test: basic A record
result=$(dig @127.0.0.1 -p 1053 example.com A +short 2>/dev/null)
if echo "$result" | grep -q "192.0.2.1"; then
    echo "PASS: A record resolved correctly"
else
    echo "FAIL: expected 192.0.2.1, got: $result"
    kill $SERVER_PID 2>/dev/null || true
    exit 1
fi

# Smoke test: CNAME chain resolution
result=$(dig @127.0.0.1 -p 1053 blog.example.com A +short 2>/dev/null)
if echo "$result" | grep -q "192.0.2.1"; then
    echo "PASS: CNAME chain resolution works"
else
    echo "FAIL: CNAME chain issue, got: $result"
    kill $SERVER_PID 2>/dev/null || true
    exit 1
fi

# Smoke test: NXDOMAIN with SOA
result=$(dig @127.0.0.1 -p 1053 nonexistent.example.com A 2>/dev/null)
if echo "$result" | grep -q "NXDOMAIN" && echo "$result" | grep -q "SOA"; then
    echo "PASS: NXDOMAIN with SOA works"
else
    echo "FAIL: NXDOMAIN/SOA issue"
    kill $SERVER_PID 2>/dev/null || true
    exit 1
fi

# Verify compliance report exists and is structurally valid
python3 -c "
import json, sys
with open('/app/compliance_report.json') as f:
    report = json.load(f)
assert isinstance(report, list), 'Report must be a list'
assert len(report) >= 4, f'Expected >=4 violations, got {len(report)}'
required = {'violation', 'rfc', 'section', 'severity', 'fix_description'}
for i, entry in enumerate(report):
    missing = required - set(entry.keys())
    assert not missing, f'Entry {i} missing fields: {missing}'
print(f'PASS: Compliance report valid with {len(report)} violations')
"

kill $SERVER_PID 2>/dev/null || true
echo "Solution deployed and verified successfully"
