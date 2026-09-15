#!/bin/bash

set -e

# Create working directories
mkdir -p /app/evidence /app/artifacts /app/detection

# Download PCAP evidence file
wget -q -O /app/evidence/infected.pcap "https://forensicscontest.com/contest05/infected.pcap"

# Verify download integrity
PCAP_MD5=$(md5sum /app/evidence/infected.pcap | awk '{print $1}')
if [ "$PCAP_MD5" != "c09a3019ada7ab17a44537b069480312" ]; then
    echo "ERROR: PCAP download corrupted (MD5: $PCAP_MD5)"
    exit 1
fi

# Phase 1: Forensic analysis and artifact extraction
python3 /solution/analyze.py

# Phase 2: YARA detection engineering and threat assessment
python3 /solution/detection.py
