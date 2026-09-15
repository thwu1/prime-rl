#!/usr/bin/env bash

set -e

pip3 install numpy==2.1.3 -q

# Deploy fixed C source
cp /solution/cubic_core_fixed.c /app/cubic_core.c

# Fix the Makefile: add -fPIC and -lm
cat > /app/Makefile << 'MAKEOF'
CC = gcc
CFLAGS = -O2 -Wall -fPIC
TARGET = libcubic.so

all: $(TARGET)

$(TARGET): cubic_core.c
	$(CC) $(CFLAGS) -shared -o $@ $< -lm

clean:
	rm -f $(TARGET)
MAKEOF

# Build the shared library
cd /app && make clean && make

# Deploy fixed Python module
cp /solution/eos_engine_fixed.py /app/eos_engine.py

echo "Solution deployed."
