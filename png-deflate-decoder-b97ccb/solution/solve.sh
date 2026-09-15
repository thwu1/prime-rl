#!/bin/bash

# Deploy the complete PNG decoder implementation and fixed Makefile
cp /solution/decode_png_complete.c /app/decode_png.c
cp /solution/Makefile /app/Makefile

# Build CLI tool and shared library
cd /app && make clean && make
