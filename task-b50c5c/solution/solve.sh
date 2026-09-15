#!/bin/bash

# Copy Chess960-capable C source, header, ctypes bridge, and updated Makefile
cp /solution/perft960.c /app/perft.c
cp /solution/perft960.h /app/perft960.h
cp /solution/perft_bridge.py /app/perft_bridge.py
cp /solution/Makefile.960 /app/Makefile

# Build both standalone binary and shared library
cd /app
make clean
make all

# Run Valgrind memcheck on a Chess960 position at depth 3
valgrind --tool=memcheck --leak-check=full \
    --log-file=/app/valgrind_report.txt \
    ./perft "nrkbbqrn/pppppppp/8/8/8/8/PPPPPPPP/NRKBBQRN w BGbg - 0 1" 3

# Generate results.json via the Python ctypes bridge
python3 /solution/make_results.py
