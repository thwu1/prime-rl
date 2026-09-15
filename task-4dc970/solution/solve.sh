#!/bin/bash

# Compile C extension for nibble packing
gcc -shared -fPIC -O2 -o /app/libnibble.so /app/nibble_pack.c

# Deploy solution codec
cp /solution/codec.py /app/codec.py
