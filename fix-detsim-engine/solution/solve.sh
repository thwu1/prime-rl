#!/bin/bash

# Restore original buggy source to /app/ from safe backup
cp -r /opt/task-src/* /app/
mkdir -p /app/results

# Apply all bug fixes (5 bugs across detsim/, replication/, checker/)
python3 /solution/fix_all.py

# Install the campaign config
cp /solution/campaign_config.json /app/campaign_config.json

# Generate the correctness analysis report
python3 /solution/write_analysis.py
