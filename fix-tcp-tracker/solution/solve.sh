#!/bin/bash

pip3 install scapy==2.6.1 -q

# Install the fixed and extended tracker
cp /solution/fixed_tracker.py /app/tcp_tracker.py

# Generate reorder.pcap test capture
python3 /solution/generate_reorder.py

# Run the tracker on all captures (including reorder.pcap)
python3 /app/tcp_tracker.py /app/captures/

# Generate cross-validation report against tshark
python3 /solution/cross_validate.py
