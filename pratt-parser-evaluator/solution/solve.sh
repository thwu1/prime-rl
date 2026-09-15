#!/bin/bash

# Copy solution source files to /app/
cp /solution/tokens.h /app/tokens.h
cp /solution/lexer.l /app/lexer.l
cp /solution/minipratt.c /app/minipratt.c

# Build the project
make -C /app clean
make -C /app

# Verify on examples
for f in /app/examples/*.mp; do
    echo "$(basename "$f"): $(/app/minipratt "$f")"
done
