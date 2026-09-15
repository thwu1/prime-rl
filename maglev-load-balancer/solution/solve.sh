#!/bin/bash

# Deploy the load balancer implementation
cp /solution/solution.py /app/balancer.py

# Fix the nginx configuration
cp /solution/nginx_fixed.conf /app/nginx/nginx.conf

# Run PCAP analysis
python3 /solution/analyze_pcap.py
