#!/bin/bash

# Calibrate disaggregated-memory bandwidth using iperf3

# Start iperf3 server in daemon mode
iperf3 -s -D -p 5201
sleep 1

# Run measurement (2-second TCP throughput test)
iperf3 -c 127.0.0.1 -p 5201 -t 2 -J > /tmp/iperf3_result.json 2>/dev/null

# Stop server
pkill -f "iperf3 -s" 2>/dev/null || true

# Parse results and write calibration file
python3 /solution/parse_calibration.py /tmp/iperf3_result.json /opt/llm-sim/calibration.json
