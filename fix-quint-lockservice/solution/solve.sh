#!/bin/bash

cd /app

# Write the corrected specification and diagnosis
python3 /solution/implement_spec.py

# Verify the implementation
echo "=== Type checking ==="
quint typecheck /app/lock_manager.qnt

echo "=== Testing singleLeader ==="
quint run /app/lock_manager.qnt --invariant=singleLeader --max-steps=20 --max-samples=200

echo "=== Testing epochMonotonicity ==="
quint run /app/lock_manager.qnt --invariant=epochMonotonicity --max-steps=20 --max-samples=200

echo "=== Testing fencingTokenOrder ==="
quint run /app/lock_manager.qnt --invariant=fencingTokenOrder --max-steps=20 --max-samples=200

echo "=== Testing splitBrainPrevention ==="
quint run /app/lock_manager.qnt --invariant=splitBrainPrevention --max-steps=20 --max-samples=200

echo "=== Testing voteConsistency ==="
quint run /app/lock_manager.qnt --invariant=voteConsistency --max-steps=20 --max-samples=200

echo "=== All verification checks passed ==="
