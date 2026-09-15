#!/bin/bash

cd /app

# Build the stress-test IR generator and produce missing programs
make generate

# Deploy the reference allocator
cp /solution/allocator_impl.py /app/allocator.py
