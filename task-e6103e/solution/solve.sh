#!/usr/bin/env bash

# Compile the C helper library
cd /app
make

# Install the sorted set implementation
cp /solution/sorted_set_impl.py /app/sorted_set.py

# Install the complete Lua validation script
cp /solution/bulk_validate_complete.lua /app/bulk_validate.lua
