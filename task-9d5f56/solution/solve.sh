#!/bin/bash

set -e

# Download DerivedCoreProperties.txt (InCB data for GB9c rule)
curl -sL "https://www.unicode.org/Public/UCD/latest/ucd/DerivedCoreProperties.txt" \
    -o /app/testdata/DerivedCoreProperties.txt

# Install C source, Makefile, and Python wrapper
cp /solution/propdb.c /app/propdb.c
cp /solution/Makefile.solution /app/Makefile
cp /solution/segmenter_impl.py /app/segmenter.py

# Build the C shared library using Makefile with pkg-config for ICU flags
cd /app
make

# Verify the library was built and links against ICU
ls -la /app/libpropdb.so
ldd /app/libpropdb.so | grep libicuuc

echo "Solution installed and built successfully."
