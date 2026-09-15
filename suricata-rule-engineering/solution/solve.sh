#!/bin/bash

set -euo pipefail

# ------------------------------------------------------------------
# Step 1: Analyze PCAP, diagnose deployed rule bugs, write corrections
# ------------------------------------------------------------------
python3 /solution/diagnose_and_fix.py

# ------------------------------------------------------------------
# Step 2: Validate corrected rules
# ------------------------------------------------------------------
echo "Validating rules..."
suricata -T \
    -S /app/rules/local.rules \
    -l /app/logs/ \
    -k none \
    -c /app/suricata.yaml

echo "Rule validation passed."

# ------------------------------------------------------------------
# Step 3: Run Suricata against the incident PCAP
# ------------------------------------------------------------------
rm -f /app/logs/eve.json /app/logs/fast.log

echo "Running Suricata against incident.pcap..."
suricata -r /app/incident.pcap \
    -S /app/rules/local.rules \
    -l /app/logs/ \
    -k none \
    -c /app/suricata.yaml \
    --runmode single

echo "Suricata run complete."

# ------------------------------------------------------------------
# Step 4: Generate incident report from EVE JSON analysis
# ------------------------------------------------------------------
python3 /solution/gen_report.py

echo "Done. Check /app/incident_report.txt for findings."
