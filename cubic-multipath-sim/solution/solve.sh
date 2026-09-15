#!/bin/bash

# Deploy the CUBIC congestion control simulator
cp /solution/simulator.py /app/simulator.py

# Verify the solution works with a test scenario
python3 -c "
import json, sys
scenario = {
    'params': {
        'mss_bytes': 1200, 'cubic_C': 0.4, 'cubic_beta': 0.7,
        'ecn_beta': 0.85, 'initial_cwnd_mss': 10
    },
    'paths': [
        {'id': 0, 'rtt_ms': 50},
        {'id': 1, 'rtt_ms': 100}
    ],
    'events': [
        {'time_ms': 100, 'type': 'loss', 'path_id': 0},
        {'time_ms': 110, 'type': 'spurious_recovery', 'path_id': 0},
        {'time_ms': 500, 'type': 'ecn', 'path_id': 1},
        {'time_ms': 2000, 'type': 'loss', 'path_id': 0},
        {'time_ms': 3000, 'type': 'loss', 'path_id': 1}
    ],
    'duration_ms': 10000
}
with open('/tmp/verify_scenario.json', 'w') as f:
    json.dump(scenario, f)
"

python3 /app/simulator.py --scenario /tmp/verify_scenario.json --output /tmp/verify_output.json

# Validate the output
python3 -c "
import json, sys
with open('/tmp/verify_output.json') as f:
    result = json.load(f)

# Basic structural checks
assert 'paths' in result, 'Missing paths'
assert '0' in result['paths'], 'Missing path 0'
assert '1' in result['paths'], 'Missing path 1'
assert result['total_bytes_delivered'] > 0, 'No bytes delivered'

p0 = result['paths']['0']
p1 = result['paths']['1']

# Path 0: 2 losses, 1 spurious recovery
assert p0['loss_events'] == 2, f'Path 0 losses: {p0[\"loss_events\"]}'
assert p0['spurious_recoveries'] == 1, f'Path 0 spurious: {p0[\"spurious_recoveries\"]}'

# Path 1: 1 loss, 1 ECN
assert p1['loss_events'] == 1, f'Path 1 losses: {p1[\"loss_events\"]}'
assert p1['ecn_events'] == 1, f'Path 1 ECN: {p1[\"ecn_events\"]}'

# Multipath schedule should have entries for both paths
sched = result['multipath_schedule']
assert '0' in sched or 0 in sched, 'Missing schedule for path 0'
assert '1' in sched or 1 in sched, 'Missing schedule for path 1'

print('All verification checks passed.')
print(json.dumps(result, indent=2))
"

echo "Solution deployed and verified successfully."
