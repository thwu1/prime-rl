#!/bin/bash

pip3 install numpy==1.26.4 scipy==1.13.1 matplotlib==3.9.2 -q

cp /solution/rt_analysis.py /app/rt_analysis.py

# Run data generation and analysis in a single Python process to avoid
# any inter-process filesystem visibility issues.
python3 << 'PYEOF'
import importlib.util, sys, os

# --- Generate data ---
gen_path = None
for candidate in ['/opt/generate_data.py', '/app/generate_data.py']:
    if os.path.exists(candidate):
        gen_path = candidate
        break

if gen_path is None:
    print('ERROR: generate_data.py not found at /opt or /app', file=sys.stderr)
    sys.exit(1)

spec = importlib.util.spec_from_file_location('generate_data', gen_path)
gen_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen_mod)
gen_mod.generate()

# --- Verify data files ---
for fn in ['dose_primary.json', 'dose_secondary.json', 'dose_boost.json',
           'structures.json', 'protocol.json']:
    fp = os.path.join('/app/data', fn)
    if not os.path.exists(fp):
        print(f'ERROR: {fp} not found after generation', file=sys.stderr)
        if os.path.isdir('/app/data'):
            print(f'Contents of /app/data: {os.listdir("/app/data")}', file=sys.stderr)
        else:
            print('/app/data directory does not exist', file=sys.stderr)
        sys.exit(1)

# --- Run analysis ---
sys.path.insert(0, '/app')
import rt_analysis
rt_analysis.main()
PYEOF
