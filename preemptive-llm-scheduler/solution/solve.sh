#!/bin/bash

# Step 1: Calibrate bandwidth using iperf3
/solution/calibrate.sh

# Step 2: Deploy the scheduler
cp /solution/scheduler_impl.py /opt/llm-sim/scheduler/paged_mlfq.py

# Step 3: Run comparison
cd /opt/llm-sim && python3 run.py compare
