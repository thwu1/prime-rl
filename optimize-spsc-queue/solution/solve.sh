#!/bin/bash

mkdir -p /app/include

# Apply fixed implementations over the buggy originals.
cp /solution/fixed_spsc_queue.h /app/include/spsc_queue.h
cp /solution/fixed_shm_protocol.h /app/include/shm_protocol.h
cp /solution/config.h /app/include/config.h
cp /solution/Makefile /app/Makefile

# Verify stress test passes with the fixed code.
cd /app && make stress

# Write the diagnostic analysis report.
cp /solution/analysis.md /app/analysis.md
