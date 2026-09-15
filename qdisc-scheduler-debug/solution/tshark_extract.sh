#!/bin/bash
# Extract per-packet fields from capture.pcap using tshark and
# transform into trace.csv for the hierarchical shaper.
#

set -e

# Use tshark to extract per-packet fields from the pcap:
#   frame.time_epoch  — packet timestamp as epoch seconds (float)
#   udp.srcport       — UDP source port (encodes flow_id)
#   ip.dsfield.dscp   — DSCP value from IP header
#   ip.len            — IP total length (= size_bytes for the shaper)
tshark -r /app/capture.pcap \
  -Y "udp" \
  -T fields \
  -e frame.time_epoch \
  -e udp.srcport \
  -e ip.dsfield.dscp \
  -e ip.len \
  -E separator=, \
  -E quote=n \
  > /tmp/tshark_raw.csv

# Transform tshark output into trace.csv format:
#   arrival_ns  — nanosecond timestamp (epoch_seconds * 1e9)
#   flow_id     — derived from src_port (flow_id = src_port - 10000)
#   size_bytes  — IP total length
#   dscp        — DSCP code point
python3 -c "
import csv
import sys

with open('/tmp/tshark_raw.csv') as fin, \
     open('/app/trace.csv', 'w', newline='') as fout:
    writer = csv.DictWriter(fout,
                            ['arrival_ns', 'flow_id', 'size_bytes', 'dscp'])
    writer.writeheader()
    for line in fin:
        parts = line.strip().split(',')
        if len(parts) != 4 or not parts[0]:
            continue
        try:
            ts_epoch = float(parts[0])
            src_port = int(parts[1])
            dscp = int(parts[2])
            ip_len = int(parts[3])
        except (ValueError, IndexError):
            continue

        writer.writerow({
            'arrival_ns': int(round(ts_epoch * 1e9)),
            'flow_id': src_port - 10000,
            'size_bytes': ip_len,
            'dscp': dscp,
        })
"

echo "Extracted $(tail -n +2 /app/trace.csv | wc -l) packets to /app/trace.csv"
