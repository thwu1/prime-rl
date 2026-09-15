#!/usr/bin/env python3
"""Apply fixes to the 3 bugs in /app/cffwis.py.

Bug 1 (DC Eq.19): Divisor is 4000 instead of 400 in moisture equivalent
Bug 2 (ISI Eq.26): Wind speed divided by 3.6 (unnecessary unit conversion)
Bug 3 (DMC Eq.15): Uses math.log10 instead of math.log (natural logarithm)
"""


with open('/app/cffwis.py', 'r') as f:
    code = f.read()

# Bug 1: DC Eq.19 — moisture equivalent divisor
# exp(-dc0/4000.0) should be exp(-dc0/400.0)
code = code.replace(
    'math.exp(max(-dc0 / 4000.0, -700))',
    'math.exp(max(-dc0 / 400.0, -700))'
)

# Bug 2: ISI Eq.26 — wind speed is already in km/h, no /3.6 conversion
code = code.replace(
    'math.exp(0.05039 * ws / 3.6)',
    'math.exp(0.05039 * ws)'
)

# Bug 3: DMC Eq.15 — natural log (math.log), not common log (math.log10)
code = code.replace(
    '43.43 * (5.6348 - math.log10(wmr - 20.0))',
    '43.43 * (5.6348 - math.log(wmr - 20.0))'
)

with open('/app/cffwis.py', 'w') as f:
    f.write(code)

print("All 3 bugs fixed in /app/cffwis.py")
