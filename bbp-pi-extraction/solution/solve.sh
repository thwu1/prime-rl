#!/bin/bash

# Install the correct BBP implementation and build
cp /solution/pi_extract_impl.c /app/pi_extract.c
cd /app && make clean && make
