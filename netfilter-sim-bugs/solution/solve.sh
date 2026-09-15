#!/bin/bash

set -e

echo "=== Step 1: Fix netfilter simulator bugs ==="
python3 /solution/fix_bugs.py

echo ""
echo "=== Step 2: Verify scenarios pass ==="
python3 /app/run_sim.py

echo ""
echo "=== Step 3: Fix evaluate.py match functions ==="
python3 /solution/fix_evaluate.py

echo ""
echo "=== Step 4: Analyze traffic capture ==="
echo "--- Protocol breakdown ---"
tshark -r /app/captures/traffic.pcap -q -z io,phs 2>/dev/null || true
echo ""
echo "--- Top source networks by packet count ---"
tshark -r /app/captures/traffic.pcap -T fields -e ip.src -e ip.proto -e tcp.dstport -e udp.srcport 2>/dev/null | \
    awk '{print $1}' | cut -d. -f1-2 | sort | uniq -c | sort -rn | head -20 || true
echo ""
echo "--- UDP payload size distribution ---"
tshark -r /app/captures/traffic.pcap -Y "udp" -T fields -e ip.src -e udp.srcport -e udp.length 2>/dev/null | \
    sort -t$'\t' -k3 -n | head -20 || true

echo ""
echo "=== Step 5: Write attack classification ==="
python3 /solution/write_classification.py

echo ""
echo "=== Step 6: Evaluate all strategies ==="
python3 /solution/evaluate_strategies.py

echo ""
echo "=== Step 7: Design optimal mitigation rules ==="
python3 /solution/design_rules.py

echo ""
echo "=== Done ==="
