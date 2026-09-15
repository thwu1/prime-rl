#!/bin/bash


pip3 install numpy==2.1.3 -q

# Fix the polar solver (4 issues: transpose check, R update formula,
# stability denominator, optimal restart search unimplemented)
cp /solution/polar_solver_fixed.py /app/polar_solver.py

# Install the coefficient designer implementation
cp /solution/coefficient_designer_impl.py /app/coefficient_designer.py

# Design and save the custom coefficient schedule
cd /app && python3 -c "
from coefficient_designer import design_custom_schedule, save_config, load_matrix_specs, evaluate_schedule
import json
specs = load_matrix_specs()
with open('/app/design_spec.json') as f:
    design_spec = json.load(f)
coefficients = design_custom_schedule(specs, design_spec)
save_config(coefficients, 'custom_optimized', '/app/configs/custom_optimized.json')
error = evaluate_schedule(coefficients, specs)
print('Custom schedule average error: %.6f' % error)
"

# Fix the jq extract filter (wrong path into nested JSON)
cp /solution/extract_fixed.jq /app/scripts/extract.jq

# Fix the sqlite3 import script (wrong jq field name for matrix specs)
cp /solution/import_data_fixed.sh /app/scripts/import_data.sh

# Fix the jq report filter (missing rank computation and JSON parsing)
cp /solution/report_fixed.jq /app/scripts/report.jq

# Fix the Makefile (wrong sqlite3 flag, wrong stability dependency)
cp /solution/Makefile_fixed /app/Makefile

# Run the full pipeline
make -C /app clean
make -C /app all
