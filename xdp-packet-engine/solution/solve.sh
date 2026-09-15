#!/bin/bash

# Copy the complete solution into place and build
cp /solution/pkt_engine_solution.c /app/pkt_engine.c
cd /app && make
