#!/bin/bash

# Copy optimized source into place and build
cp /solution/optimized_pipeline.cpp /app/pipeline.cpp
cd /app
make clean
make
