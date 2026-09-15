#!/bin/bash

set -e

# Run the repair/completion script for both specifications
python3 /solution/fix_spec.py

# Verify: run SANY syntax check on both specs
echo "=== Running SANY on ticket_lock ==="
cd /app/spec
java -cp /opt/tla2tools.jar tla2sany.SANY ticket_lock.tla

echo ""
echo "=== Running SANY on rwlock ==="
java -cp /opt/tla2tools.jar tla2sany.SANY rwlock.tla

# Verify: run TLC model checking on both specs
echo ""
echo "=== Running TLC on ticket_lock ==="
java -cp /opt/tla2tools.jar tlc2.TLC \
    -config ticket_lock.cfg \
    -workers 1 \
    ticket_lock.tla

echo ""
echo "=== Running TLC on rwlock ==="
java -cp /opt/tla2tools.jar tlc2.TLC \
    -config rwlock.cfg \
    -workers 1 \
    rwlock.tla
