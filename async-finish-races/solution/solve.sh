#!/bin/bash

set -e

# Copy solution scripts to /app/
cp /solution/graph_utils.py /app/graph_utils.py
cp /solution/analyzer.py /app/analyzer.py
cp /solution/visualizer.py /app/visualizer.py
cp /solution/scheduler.py /app/scheduler.py

# Create directories
mkdir -p /app/graphs /app/schedules

# Create Makefile
cat > /app/Makefile << 'MAKEFILE_END'
.PHONY: all analyze visualize schedule report

all: analyze visualize schedule report

analyze:
	python3 /app/analyzer.py

visualize:
	python3 /app/visualizer.py

schedule:
	python3 /app/scheduler.py

report:
	jq -s '.[0] as $$r | .[1] as $$s | reduce ($$r | keys[]) as $$k ({}; .[$$k] = ($$r[$$k] + $$s[$$k]))' /app/results.json /app/schedules/summary.json > /app/report.json
MAKEFILE_END

# Run the pipeline
cd /app && make all
