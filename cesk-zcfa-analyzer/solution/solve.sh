#!/bin/bash

# Copy solution implementations to /app
cp /solution/interp_impl.py /app/interp.py
cp /solution/analyzer_impl.py /app/analysis.py
cp /solution/gen_graph.py /app/gen_graph.py

# Generate flow graph visualization
cd /app
python3 /app/gen_graph.py

# Sanity check
python3 -c "
from interp import run
assert run('(+ 3 4)') == 7, 'Interpreter basic test failed'
print('Interpreter sanity check passed')

from analysis import analyze
flow = analyze('(let ((f (lambda (x) x))) (f 10))')
assert 1 in flow.get('f', set()), 'Analysis basic test failed'
print('Analysis sanity check passed')

import os
assert os.path.isfile('/app/flow_graph.dot'), 'DOT file missing'
assert os.path.isfile('/app/flow_graph.svg'), 'SVG file missing'
print('Graph files sanity check passed')
"
