#!/bin/bash

set -euo pipefail

cd /app

# Fix recorder.c and replayer.c bugs
python3 /solution/fix_bugs.py

# Install migrator and validator sources
cp /solution/migrator.c /app/migrator.c
cp /solution/validator.c /app/validator.c

# Update Makefile: add migrator and validator to all and clean targets
if ! grep -q 'migrator' /app/Makefile; then
    sed -i 's/^all: recorder replayer$/all: recorder replayer migrator validator/' /app/Makefile
    sed -i 's/rm -f recorder replayer/rm -f recorder replayer migrator validator/' /app/Makefile
    echo "" >> /app/Makefile
    echo "migrator: migrator.c" >> /app/Makefile
    printf '\t$(CC) $(CFLAGS) -o $@ $<\n' >> /app/Makefile
    echo "" >> /app/Makefile
    echo "validator: validator.c" >> /app/Makefile
    printf '\t$(CC) $(CFLAGS) -o $@ $<\n' >> /app/Makefile
fi

# Rebuild everything
make clean all

# Generate the architectural analysis document
python3 /solution/write_analysis.py
