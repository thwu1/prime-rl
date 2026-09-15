#!/bin/bash

pip3 install requests==2.32.3 -q

# Fix all bugs in the emulator
python3 /solution/fix_emulator.py

# Generate conformance database and reports
python3 /solution/generate_reports.py

# Generate unified diff of emulator changes
diff -u /app/cpu6502_original.py /app/cpu6502.py > /app/emulator_changes.patch || true
