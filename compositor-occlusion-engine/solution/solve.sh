#!/bin/bash

# Copy C source and header, then build the shared library
cp /solution/region.h /app/region.h
cp /solution/region.c /app/region.c
cd /app && make

# Copy Python modules
cp /solution/engine.py /app/engine.py
cp /solution/compositor.py /app/compositor.py
chmod +x /app/compositor.py
