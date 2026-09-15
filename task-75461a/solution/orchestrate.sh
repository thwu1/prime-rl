#!/bin/bash
# Orchestration script — runs INSIDE a Flux instance.
# Starts queues, applies drain states, submits verification jobs,
# and writes a scheduling report to /app/scheduling_report.json.
#

set -e

echo "=== Starting all configured queues ==="
flux queue start --all

echo "=== Applying runtime drain states ==="
flux resource drain 5 "Memory ECC error rate exceeded threshold"
flux resource drain 7 "GPU thermal throttling detected"

echo "=== Waiting for state to settle ==="
sleep 2

echo "=== Current queue status ==="
flux queue list

echo "=== Current resource status ==="
flux resource status

echo "=== Current drain status ==="
flux resource drain

echo "=== Submitting verification jobs ==="

# All jobs must specify a duration within queue policy limits.
# batch: 8h max, highmem: 48h max, gpu: 4h max.

# Job 1: batch queue
echo "  Submitting to batch queue..."
batch_id=$(flux submit -q batch -t 1m -n1 true)
flux job wait-event --timeout=30 "$batch_id" clean
batch_rank=$(flux jobs -no {ranks} "$batch_id")
batch_state=$(flux jobs -no {state} "$batch_id")
echo "  batch: job=$batch_id rank=$batch_rank state=$batch_state"

# Job 2: highmem queue
echo "  Submitting to highmem queue..."
highmem_id=$(flux submit -q highmem -t 1m -n1 true)
flux job wait-event --timeout=30 "$highmem_id" clean
highmem_rank=$(flux jobs -no {ranks} "$highmem_id")
highmem_state=$(flux jobs -no {state} "$highmem_id")
echo "  highmem: job=$highmem_id rank=$highmem_rank state=$highmem_state"

# Job 3: gpu queue
echo "  Submitting to gpu queue..."
gpu_id=$(flux submit -q gpu -t 1m -n1 true)
flux job wait-event --timeout=30 "$gpu_id" clean
gpu_rank=$(flux jobs -no {ranks} "$gpu_id")
gpu_state=$(flux jobs -no {state} "$gpu_id")
echo "  gpu: job=$gpu_id rank=$gpu_rank state=$gpu_state"

# Job 4: default queue (no -q flag, should route to batch)
echo "  Submitting without queue (default)..."
default_id=$(flux submit -t 1m -n1 true)
flux job wait-event --timeout=30 "$default_id" clean
default_rank=$(flux jobs -no {ranks} "$default_id")
default_state=$(flux jobs -no {state} "$default_id")
echo "  default: job=$default_id rank=$default_rank state=$default_state"

# Collect drain and exclude information
drain_ranks=$(flux resource status -s drain -no {ranks} 2>/dev/null || echo "")
exclude_ranks=$(flux resource status -s exclude -no {ranks} 2>/dev/null || echo "")

echo ""
echo "=== Writing scheduling report ==="

# Use Python to produce well-formed JSON from the collected variables
python3 -c "
import json, subprocess

def flux_query(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    return r.stdout.strip()

# Collect drain details
drain_list = []
drain_output = flux_query('flux resource drain -no \"{ranks} {reason}\"')
for line in drain_output.split('\n'):
    line = line.strip()
    if line:
        parts = line.split(None, 1)
        if len(parts) >= 2:
            drain_list.append({'ranks': parts[0], 'reason': parts[1]})

report = {
    'queues': ['batch', 'highmem', 'gpu'],
    'exclude_ranks': '${exclude_ranks}',
    'drain': drain_list,
    'jobs': {
        'batch': {
            'job_id': '${batch_id}',
            'queue': 'batch',
            'ranks': '${batch_rank}',
            'state': '${batch_state}'
        },
        'highmem': {
            'job_id': '${highmem_id}',
            'queue': 'highmem',
            'ranks': '${highmem_rank}',
            'state': '${highmem_state}'
        },
        'gpu': {
            'job_id': '${gpu_id}',
            'queue': 'gpu',
            'ranks': '${gpu_rank}',
            'state': '${gpu_state}'
        },
        'default': {
            'job_id': '${default_id}',
            'queue': 'batch (default)',
            'ranks': '${default_rank}',
            'state': '${default_state}'
        }
    }
}

with open('/app/scheduling_report.json', 'w') as f:
    json.dump(report, f, indent=2)

print(json.dumps(report, indent=2))
print('\nReport written to /app/scheduling_report.json')
"

echo "=== Orchestration complete ==="
