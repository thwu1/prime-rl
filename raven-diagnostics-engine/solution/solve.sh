#!/bin/bash


# Copy solution files to /app
cp /solution/diag_engine.c /app/diag_engine.c
cp /solution/app_Makefile /app/Makefile
cp /solution/raven_diag_impl.py /app/raven_diag.py
chmod +x /app/raven_diag.py

# Build the shared library
make -C /app build
