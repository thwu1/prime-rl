#!/bin/bash

# Convert pcapng captures to pcap for uniform binary parsing
for f in /app/data/captures/*.pcapng; do
    if [ -f "$f" ]; then
        base=$(basename "$f" .pcapng)
        editcap -F pcap "$f" "/app/data/captures/${base}_converted.pcap"
    fi
done

# Deploy pipeline and run
cp /solution/pipeline.py /app/tools/pipeline.py
cd /app
python3 /app/tools/pipeline.py
