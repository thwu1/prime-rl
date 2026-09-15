#!/bin/bash

# Create source directory and copy solution source
mkdir -p /app/src
cp /solution/bjoint.py /app/src/bjoint.py
cp /solution/Makefile /app/Makefile

# Build using make
cd /app && make
