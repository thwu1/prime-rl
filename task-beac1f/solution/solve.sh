#!/bin/bash

# Install the complete pledge() implementation
cp /solution/pledge_impl.c /app/pledge.c

# Build
cd /app
make clean all

# Verify
./test_harness
