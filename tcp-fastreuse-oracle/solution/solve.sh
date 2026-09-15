#!/bin/bash

# Deploy the pipeline components to /app/
cp /solution/oracle.py /app/oracle.py
cp /solution/strace_parser.py /app/strace_parser.py
cp /solution/ss_parser.py /app/ss_parser.py
chmod +x /app/oracle.py /app/strace_parser.py /app/ss_parser.py

# Smoke test: parse a capture, run oracle, parse ss output
python3 /app/strace_parser.py /app/captures/capture_01.strace /app/scenario.json \
    --ephemeral-lo 60000 --ephemeral-hi 60000

python3 /app/oracle.py

python3 /app/ss_parser.py /app/captures/capture_01.ss /app/connections.json

# Verify pipeline output
python3 -c "
import json, sys

with open('/app/results.json') as f:
    r = json.load(f)

assert 'steps' in r, 'Missing steps'
assert 'final_buckets' in r, 'Missing final_buckets'

for step in r['steps']:
    assert step['outcome'] == 'success', f'Step {step[\"step\"]} failed'

fb = r['final_buckets']
assert '60000' in fb, f'Missing bucket: {fb}'
assert fb['60000']['fastreuse'] == 0, f'Wrong fastreuse: {fb}'
assert fb['60000']['num_owners'] == 2, f'Wrong owners: {fb}'

with open('/app/connections.json') as f:
    conns = json.load(f)
assert len(conns) == 2, f'Expected 2 connections, got {len(conns)}'

print('Pipeline smoke test passed')
"
