#!/usr/bin/env bash

cd /app

# Install the new modules
cp /solution/value_resolver.py /app/value_resolver.py
cp /solution/inheritance.py /app/inheritance.py

# Replace resolver.py with the extended version
cp /solution/resolver_patched.py /app/resolver.py
