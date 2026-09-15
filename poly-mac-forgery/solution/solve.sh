#!/bin/bash

cd /app

# Step 1: Extract authenticated messages from network capture using tshark
# Filter UDP port 4443, output raw payload hex
tshark -r /app/capture/traffic.pcap \
    -Y "udp.dstport == 4443" \
    -T fields -e udp.payload 2>/dev/null > /tmp/pcap_payloads.txt

# Fallback: try 'data' field if udp.payload is empty
if [ ! -s /tmp/pcap_payloads.txt ]; then
    tshark -r /app/capture/traffic.pcap \
        -Y "udp.dstport == 4443" \
        -T fields -e data 2>/dev/null > /tmp/pcap_payloads.txt
fi

# Step 2: Query session database for target ciphertext and nonce
sqlite3 /app/db/sessions.db \
    "SELECT ciphertext_hex FROM targets WHERE target_id = 99;" \
    > /tmp/target_ct.txt

sqlite3 /app/db/sessions.db \
    "SELECT s.nonce_hex FROM targets t JOIN sessions s ON t.session_id = s.session_id WHERE t.target_id = 99;" \
    > /tmp/target_nonce.txt

# Step 3: Disassemble MAC engine to extract GF(2^64) reduction polynomial
objdump -d /app/bin/mac_engine > /tmp/mac_disasm.txt

# Step 4: Run cryptographic attack using extracted data
python3 /solution/solve_forgery.py
