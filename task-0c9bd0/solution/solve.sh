#!/usr/bin/env bash

# Copy solution files into place
cp /solution/fp8_impl.c /app/fp8.c
cp /solution/fp8_ctypes_impl.py /app/fp8_ctypes.py
cp /solution/fp8_adder_impl.v /app/fp8_adder.v

# Write the Makefile build rule
cat > /app/Makefile << 'MKEOF'
CC = gcc
CFLAGS = -Wall -Wextra -O2 -fPIC
TARGET = libfp8.so

all: $(TARGET)

$(TARGET): fp8.c fp8_api.h
	$(CC) $(CFLAGS) -shared -o $@ fp8.c -lm

clean:
	rm -f $(TARGET) *.o

.PHONY: all clean
MKEOF

# Build the C shared library
make -C /app clean all

# Verify the library was built
ls -la /app/libfp8.so

# Quick smoke test: compile and run the Verilog adder
iverilog -o /tmp/fp8_sim /app/fp8_adder.v /tests/fp8_adder_tb.v
vvp /tmp/fp8_sim
