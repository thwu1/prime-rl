#!/bin/bash

pip3 install pytest==8.3.4 -q

cd /app

# Run the pipeline process command
python3 /app/gnss_pipeline.py process \
  --nav /app/data/mixed.25n /app/data/gps_v2.99n \
  --db /app/output/gnss.db \
  --report /app/output/report.json

# Run the pipeline convert command
python3 /app/gnss_pipeline.py convert \
  --input /app/data/gps_v2.99n \
  --output /app/output/converted.25n

# Run the pipeline export command
python3 /app/gnss_pipeline.py export \
  --db /app/output/gnss.db \
  --sp3 /app/output/orbits.sp3

# Run the pipeline validate command
python3 /app/gnss_pipeline.py validate \
  --db /app/output/gnss.db \
  --sp3 /app/output/orbits.sp3 \
  --output /app/output/validation.json

# Run tests
RESULT=$(python3 -m pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?

echo "$RESULT"

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
