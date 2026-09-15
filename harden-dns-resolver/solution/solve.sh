#!/usr/bin/env bash

# Restore the original resolver if /app is empty
if [ ! -f /app/resolver.py ] && [ -f /opt/task/resolver.py ]; then
    mkdir -p /app
    cp /opt/task/resolver.py /app/resolver.py
fi

cd /app

# Phase 1: Investigate resolver behavior against known DNS patterns
echo "=== Baseline testing ==="
python3 resolver.py example.com 2>/dev/null || echo "example.com: FAILED"
python3 resolver.py www.google.com 2>/dev/null || echo "www.google.com: FAILED (likely CNAME)"

# Phase 2: Use dig as reference for expected behavior
echo ""
echo "=== Reference dig queries ==="
echo "--- example.com ---"
dig example.com A +short 2>/dev/null
echo "--- www.facebook.com (CNAME chain) ---"
dig www.facebook.com A +short 2>/dev/null
echo "--- Delegation trace ---"
dig example.com +trace +nodnssec 2>/dev/null | tail -10

# Phase 3: Capture resolver's DNS traffic with tshark
echo ""
echo "=== Traffic capture and analysis ==="
tshark -i any -f "udp port 53" -w /tmp/resolver_baseline.pcap -q 2>/dev/null &
TSHARK_PID=$!
sleep 2
python3 resolver.py example.com 2>/dev/null || true
sleep 2
kill "$TSHARK_PID" 2>/dev/null
wait "$TSHARK_PID" 2>/dev/null || true

echo "--- Outgoing queries ---"
tshark -r /tmp/resolver_baseline.pcap -Y "dns.flags.response == 0" \
  -T fields -e frame.number -e dns.id -e dns.qry.name -e dns.qry.type \
  2>/dev/null || true

echo ""
echo "--- EDNS0 OPT records in queries ---"
tshark -r /tmp/resolver_baseline.pcap -Y "dns.flags.response == 0 and dns.opt" \
  -T fields -e dns.qry.name -e dns.opt.udp_payload_size \
  2>/dev/null || echo "(none found — EDNS0 missing)"

# Phase 4: Apply all fixes and write audit report
echo ""
echo "=== Applying fixes ==="
python3 /solution/analyze_and_fix.py

# Phase 5: Verify fixes work
echo ""
echo "=== Verification ==="
python3 resolver.py example.com
echo "Audit and hardening complete."
