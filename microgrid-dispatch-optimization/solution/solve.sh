#!/bin/bash

pip3 install pulp==2.8.0 -q

python3 -c "
import json, sys
with open('/app/data/microgrid_stochastic.json') as f:
    d = json.load(f)
s = d['system']
required = ['electrolyzer_pwl_input_kw', 'electrolyzer_pwl_output_kwh',
            'electrolyzer_min_uptime_hours', 'electrolyzer_min_downtime_hours',
            'battery_degradation_cost_per_kwh', 'demand_charge_rate', 'reserve_fraction']
missing = [k for k in required if k not in s]
if missing:
    print(f'ERROR: Data file missing keys: {missing}', file=sys.stderr)
    sys.exit(1)
assert 'risk_parameters' in d, 'Missing risk_parameters'
print(f'Data OK: {len(d[\"scenarios\"])} scenarios, {d[\"planning_horizon_hours\"]}h horizon')
"

python3 /solution/solver.py
