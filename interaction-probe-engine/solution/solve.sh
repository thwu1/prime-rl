#!/bin/bash

set -e

export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

# Ensure playwright and browsers are available
pip3 install playwright==1.49.1 -q
playwright install 2>&1 || true

# Copy probe implementation to /app
cp /solution/probe_impl.py /app/probe.py

# Run the probe
cd /app
python3 /app/probe.py

# Verify output was generated
if [ -f /app/output/report.json ]; then
    echo "SUCCESS: report.json generated"
    python3 -c "import json; r=json.load(open('/app/output/report.json')); print('Pages:', list(r['pages'].keys())); print('Aggregate IR:', r['aggregate']['interaction_rate'])"
else
    echo "FAILURE: report.json not generated"
    exit 1
fi
