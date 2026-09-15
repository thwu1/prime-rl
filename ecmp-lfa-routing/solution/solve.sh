#!/bin/bash

# Deploy the routing engine implementation
cp /solution/routing_engine_impl.py /app/routing_engine.py

# Run the full audit pipeline: pcap parsing, visualization, report
python3 /solution/pipeline.py
