#!/bin/bash

set -e

cd /app

# Fix bugs in psychro.c
python3 /solution/fix_psychro.py

# Install correct AHU implementation
cp /solution/ahu_impl.c /app/ahu.c

# Rebuild
make clean
make
