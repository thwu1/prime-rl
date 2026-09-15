#!/bin/bash

export PYTHONPATH=/app:/opt/transport_lib:${PYTHONPATH:-}

# Install the solution: copy the complete transport implementation
cp /solution/transport_impl.py /app/transport.py

# Generate cwnd visualization using gnuplot
cd /app
python3 /solution/generate_plot.py
gnuplot /app/cwnd_plot.gp

# Verify the outputs were created
python3 -c "
import os, sys
svg = '/app/cwnd_evolution.svg'
if not os.path.isfile(svg):
    print('ERROR: cwnd_evolution.svg was not generated')
    sys.exit(1)
with open(svg) as f:
    content = f.read()
if 'gnuplot' not in content.lower():
    print('ERROR: SVG does not contain gnuplot metadata')
    sys.exit(1)
print(f'Visualization OK: {os.path.getsize(svg)} bytes')
"
