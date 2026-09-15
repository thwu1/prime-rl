#!/bin/bash

# Step 1: Repair corrupted log files
cp /solution/kafka_repair.py /app/repair_tool.py
python3 /app/repair_tool.py

# Step 2: Install broker (test.sh will start it)
cp /solution/kafka_broker.py /app/broker.py
