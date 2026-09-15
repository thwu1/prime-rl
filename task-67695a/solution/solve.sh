#!/usr/bin/env bash

# Copy solution components to /app
cp /solution/cool.l /app/cool.l
cp /solution/evaluator.py /app/evaluator.py
cp /solution/Makefile /app/Makefile
cp /solution/coolinterp /app/coolinterp
chmod +x /app/coolinterp

# Build the tokenizer from Flex specification
cd /app && make
