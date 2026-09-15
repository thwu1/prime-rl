#!/bin/bash


cd /app

# Fix all 10 bugs in the accelerometer pipeline
python3 << 'PYEOF'
# === Fix Makefile ===
path = '/app/Makefile'
with open(path, 'r') as f:
    code = f.read()

# Bug 1: Wrong source directory path
code = code.replace('SRCDIR  = /app/source', 'SRCDIR  = /app/src')

# Bug 2: CalibratorMain arguments in wrong order (output and config swapped)
code = code.replace(
    'CalibratorMain /app/data/input.csv /app/config/calibration.properties /app/data/calibrated.csv',
    'CalibratorMain /app/data/input.csv /app/data/calibrated.csv /app/config/calibration.properties'
)

with open(path, 'w') as f:
    f.write(code)
print("Makefile fixed")

# === Fix Calibrator.java ===
path = '/app/src/Calibrator.java'
with open(path, 'r') as f:
    code = f.read()

# Bug 3: Calibration applies scale before subtracting offset
# Correct model: calibrated = (raw - offset) * scale
code = code.replace('x[i] = x[i] * scale[0] - offset[0];', 'x[i] = (x[i] - offset[0]) * scale[0];')
code = code.replace('y[i] = y[i] * scale[1] - offset[1];', 'y[i] = (y[i] - offset[1]) * scale[1];')
code = code.replace('z[i] = z[i] * scale[2] - offset[2];', 'z[i] = (z[i] - offset[2]) * scale[2];')

with open(path, 'w') as f:
    f.write(code)
print("Calibrator.java fixed")

# === Fix AccStats.java ===
path = '/app/src/AccStats.java'
with open(path, 'r') as f:
    code = f.read()

# Bug 4: ENMO missing "- 1" subtraction (Euclidean Norm Minus One)
code = code.replace('enmo[i] = vm;', 'enmo[i] = vm - 1;')

# Bug 5: Percentile interpolation formula (R7: h = p*(n-1)+1, not p*n)
code = code.replace(
    'double h = percentiles[i] * n;',
    'double h = percentiles[i] * (n-1) + 1;'
)

with open(path, 'w') as f:
    f.write(code)
print("AccStats.java fixed")

# === Fix Features.java ===
path = '/app/src/Features.java'
with open(path, 'r') as f:
    code = f.read()

# Bug 6: Gravity EMA weight (0.5 -> 0.9)
code = code.replace('double weight = 0.5;', 'double weight = 0.9;')

# Bug 7: MPD exponent (2.0 -> 1.5 per Vaha-Ypya definition)
code = code.replace('Math.pow(Math.abs(diff), 2.0)', 'Math.pow(Math.abs(diff), 1.5)')

# Bug 8: Kurtosis uses simplified formula instead of R-style bias correction
code = code.replace(
    'kurt = kurt / N - 3.0;',
    'kurt = kurt * N*(N+1)/((N-1)*(N-2)*(N-3)*(N-4)) - 3*(N-1)*(N-1)/((N-2)*(N-3));'
)

# Bug 9: Missing Hann window before DFT (prevents spectral leakage)
code = code.replace(
    'windowed[i] = v[i] - vMean;',
    'windowed[i] = (v[i] - vMean) * 0.5 * (1.0 - Math.cos(2.0 * Math.PI * i / (n - 1)));'
)

with open(path, 'w') as f:
    f.write(code)
print("Features.java fixed")

# === Fix LowpassFilter.java ===
path = '/app/src/LowpassFilter.java'
with open(path, 'r') as f:
    code = f.read()

# Bug 10: Nyquist-normalized cutoff (Fc/Fs -> Fc/(Fs/2))
code = code.replace(
    'double W = Math.min(Fc / Fs, 0.999);',
    'double W = Math.min(Fc / (Fs / 2), 0.999);'
)

with open(path, 'w') as f:
    f.write(code)
print("LowpassFilter.java fixed")

print("All 10 bugs fixed")
PYEOF

echo "All fixes applied"
