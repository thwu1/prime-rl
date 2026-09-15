#!/bin/bash

# Build the C bit-pool library
cd /app && make -s

# Deploy the fixed sampler
cp /solution/sampler_fix.py /app/sampler.py
