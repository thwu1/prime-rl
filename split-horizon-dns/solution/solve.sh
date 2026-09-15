#!/usr/bin/env bash

set -euo pipefail

# Generate all correct BIND9 configuration and zone files from CSV data
python3 /solution/generate_zones.py

# Validate configuration
echo "=== Validating named.conf ==="
named-checkconf /etc/bind/named.conf

echo "=== Validating internal forward zone ==="
named-checkzone infra.example.com /etc/bind/zones/internal/db.infra.example.com

echo "=== Validating external forward zone ==="
named-checkzone infra.example.com /etc/bind/zones/external/db.infra.example.com

echo "=== Validating IPv4 reverse zone ==="
named-checkzone 1.0.10.in-addr.arpa /etc/bind/zones/internal/db.10.0.1

echo "=== Validating IPv6 reverse zone ==="
named-checkzone 0.0.0.0.0.0.0.0.0.0.0.0.0.0.d.f.ip6.arpa /etc/bind/zones/internal/db.fd00

# Stop BIND if already running
pkill named 2>/dev/null || true
sleep 1

# Ensure PID directory exists
mkdir -p /run/named

# Start BIND
echo "=== Starting BIND9 ==="
named -c /etc/bind/named.conf
sleep 2

# Verify BIND is running
if pgrep -x named > /dev/null; then
    echo "BIND9 is running."
else
    echo "ERROR: BIND9 failed to start." >&2
    exit 1
fi

# Quick sanity check
echo "=== Quick verification ==="
dig @127.0.0.1 -p 8053 ns1.infra.example.com A +short
dig @127.0.0.1 -p 8053 infra.example.com SOA +short
echo "Done."
