#!/bin/bash

# Step 1: Fix and compile the C shared library
cp /solution/atmos.c /app/src/atmos.c
cp /solution/atmos.h /app/src/atmos.h 2>/dev/null || true
mkdir -p /app/lib
gcc -shared -fPIC -o /app/lib/libatmos.so /app/src/atmos.c -lm

# Step 2: Fix the Python ET engine (correct ctypes bindings, all methods)
cp /solution/et_engine.py /app/et_engine.py

# Step 3: Fix the jq preprocessing script and generate station data
cp /solution/preprocess.sh /app/scripts/preprocess.sh
chmod +x /app/scripts/preprocess.sh
bash /app/scripts/preprocess.sh

# Step 4: Validate through computation
cd /app
python3 -c "
import sys, math
sys.path.insert(0, '/app')
from et_engine import compute_daily, compute_hourly, decompose_daily_divergence

lat = 39.4575 * math.pi / 180.0
tmin = (66.65 - 32.0) * 5.0 / 9.0
tmax = (102.80 - 32.0) * 5.0 / 9.0
ea = 1.2206674169951346
rs = 674.07 * 0.041868
uz = 4.80 * 0.44704

# Validate daily ASCE
r = compute_daily(tmin, tmax, ea, rs, uz, 3.0, 1208.5, lat, 182, 'asce')
assert abs(r['etr'] - 10.626087665395694) < 0.001, f'ASCE ETr: {r[\"etr\"]}'
print(f'Daily ASCE ETr: {r[\"etr\"]:.10f} (expected 10.6260876654)')

# Validate daily RefET
r2 = compute_daily(tmin, tmax, ea, rs, uz, 3.0, 1208.5, lat, 182, 'refet')
assert abs(r2['etr'] - 10.571314344056955) < 0.001, f'RefET ETr: {r2[\"etr\"]}'
print(f'Daily RefET ETr: {r2[\"etr\"]:.10f} (expected 10.5713143441)')

# Validate hourly
lon = -118.77388 * math.pi / 180.0
tmean_h = (91.80 - 32.0) * 5.0 / 9.0
ea_h = 1.1990099614301906
rs_h = 61.16 * 0.041868
uz_h = 3.33 * 0.44704
rh = compute_hourly(tmean_h, ea_h, rs_h, uz_h, 3.0, 1208.5, lat, lon, 182, 18.0, 'refet')
assert abs(rh['etr'] - 0.7201865213918281) < 0.001, f'Hourly RefET ETr: {rh[\"etr\"]}'
print(f'Hourly RefET ETr: {rh[\"etr\"]:.10f} (expected 0.7201865214)')

# Validate decomposition
d = decompose_daily_divergence(tmin, tmax, ea, rs, uz, 3.0, 1208.5, lat, 182, 'etr')
expected_total = 10.626087665395694 - 10.571314344056955
assert abs(d['total'] - expected_total) < 0.001
contrib_sum = sum(d[k] for k in ['air_pressure', 'es_slope', 'declination', 'solar_constant', 'clear_sky_radiation', 'residual'])
assert abs(contrib_sum - d['total']) < 1e-12
print(f'Decomposition total: {d[\"total\"]:.10f}, residual: {d[\"residual\"]:.10f}')

print('All validations passed.')
"
