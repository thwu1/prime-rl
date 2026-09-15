#!/bin/bash

# Run kafka-dump-log.sh diagnostics on each partition first
echo "=== Running kafka-dump-log.sh diagnostics ==="
for logfile in /app/kafka-data/*/00000000000000000000.log; do
    dir=$(basename "$(dirname "$logfile")")
    echo "--- $dir ---"
    kafka-dump-log.sh --files "$logfile" --print-data-log 2>&1 | head -20
    echo ""
done

# Use xxd for hex-level inspection of known corrupted regions
echo "=== Hex analysis of corrupted CRC in orders-1 ==="
xxd -s 17 -l 4 /app/kafka-data/orders-1/00000000000000000000.log

echo "=== Hex analysis of magic byte in events-2 ==="
xxd -s 16 -l 1 /app/kafka-data/events-2/00000000000000000000.log

echo "=== Hex analysis of compressed batch attributes in trades-0 ==="
xxd -s 21 -l 2 /app/kafka-data/trades-0/00000000000000000000.log

# Run the repair tool
python3 /solution/repair.py
