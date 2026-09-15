#!/bin/bash

# Copy the complete implementation
cp /solution/dirichlet_impl.c /app/dirichlet.c

# Rebuild the shared library
cd /app && make clean && make
