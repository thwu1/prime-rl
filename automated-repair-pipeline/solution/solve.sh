#!/bin/bash

# Build the automated repair pipeline by creating all module files.

mkdir -p /app/pipeline

cp /solution/coverage_impl.py /app/pipeline/coverage.py
cp /solution/fault_loc_impl.py /app/pipeline/fault_loc.py
cp /solution/mutator_impl.py /app/pipeline/mutator.py
cp /solution/repairer_impl.py /app/pipeline/repairer.py
cp /solution/minimizer_impl.py /app/pipeline/minimizer.py
cp /solution/init_impl.py /app/pipeline/__init__.py

echo "Pipeline installed. Verifying..."

cd /app
python3 -c "
from pipeline import repair_program
from pipeline.coverage import CoverageCollector
from pipeline.fault_loc import ochiai

# Quick smoke test on middle()
source = open('/app/programs/middle.py').read()
test_cases = [
    ((1, 2, 3), 2), ((3, 2, 1), 2), ((2, 1, 3), 2),
    ((1, 3, 2), 2), ((3, 1, 2), 2), ((2, 3, 1), 2),
    ((1, 1, 2), 1), ((2, 1, 1), 1), ((1, 2, 2), 2),
    ((5, 5, 5), 5),
]
repaired = repair_program(source, test_cases, 'middle')
ns = {}
exec(repaired, ns)
for args, expected in test_cases:
    assert ns['middle'](*args) == expected, f'middle{args} failed'
print('middle() repair verified.')

# gcd
source = open('/app/programs/gcd.py').read()
test_cases = [
    ((12, 8), 4), ((8, 12), 4), ((7, 5), 1),
    ((100, 75), 25), ((0, 5), 5), ((5, 0), 5),
    ((17, 17), 17), ((1, 1), 1), ((36, 24), 12),
    ((48, 18), 6),
]
repaired = repair_program(source, test_cases, 'gcd')
ns = {}
exec(repaired, ns)
for args, expected in test_cases:
    assert ns['gcd'](*args) == expected, f'gcd{args} failed'
print('gcd() repair verified.')

# power
source = open('/app/programs/power.py').read()
test_cases = [
    ((2, 0), 1), ((2, 1), 2), ((2, 3), 8), ((2, 10), 1024),
    ((3, 2), 9), ((3, 3), 27), ((5, 1), 5), ((10, 2), 100),
    ((1, 100), 1), ((7, 3), 343),
]
repaired = repair_program(source, test_cases, 'power')
ns = {}
exec(repaired, ns)
for args, expected in test_cases:
    assert ns['power'](*args) == expected, f'power{args} failed'
print('power() repair verified.')

print('All repairs successful.')
"
