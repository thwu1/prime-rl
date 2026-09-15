#!/usr/bin/env python3
"""Apply fixes to the 6 bugs in /app/fwi_calculator.py.

Bug 1 (FFMC): Rain threshold is 1.5 instead of 0.5 (Eq.2)
Bug 2 (DMC): Uses day_length_factor instead of day_length for drying rate
Bug 3 (DC):  Rain effect sign is + instead of - (Eqs.20-21)
Bug 4 (ISI): Moisture exponent is 5.13 instead of 5.31 (Eq.25)
Bug 5 (FWI): BUI threshold condition is inverted (Eq.28a/28b selection)
Bug 6 (Overwintering): Log fraction is inverted (qs/800 instead of 800/qs)
"""


with open('/app/fwi_calculator.py', 'r') as f:
    code = f.read()

# Bug 1: FFMC rain threshold (Eq.2)
# p > 1.5 should be p > 0.5, and rf = p - 1.5 should be rf = p - 0.5
code = code.replace('if p > 1.5:  # Eq.2 rain check', 'if p > 0.5:  # Eq.2 rain check')
code = code.replace('rf = p - 1.5  # Effective rainfall', 'rf = p - 0.5  # Effective rainfall')

# Bug 2: DMC drying rate lookup
# Must use day_length (6-14h range), NOT day_length_factor (-1.6 to 6.4 range)
code = code.replace(
    'dl = day_length_factor(lat, month)  # Effective day length',
    'dl = day_length(lat, month)  # Effective day length'
)

# Bug 3: DC rain effect sign (Eqs.20-21)
# Rain should DECREASE the drought code, so it must be dc0 - 400*log(...)
code = code.replace(
    'dr = dc0 + 400.0 * math.log(1.0 + (3.937 * rw) / smi)',
    'dr = dc0 - 400.0 * math.log(1.0 + (3.937 * rw) / smi)'
)

# Bug 4: ISI moisture exponent (Eq.25)
# Exponent should be 5.31 not 5.13 (transposed digits)
code = code.replace('mo ** 5.13', 'mo ** 5.31')

# Bug 5: FWI BUI threshold (Eq.28a vs 28b)
# Eq.28a applies when BUI <= 80, Eq.28b when BUI > 80
# The code has the condition inverted
code = code.replace(
    'if bui > 80.0:\n        fwi = 0.1 * isi * (0.626 * bui ** 0.809 + 2.0)  # Eq.28a',
    'if bui <= 80.0:\n        fwi = 0.1 * isi * (0.626 * bui ** 0.809 + 2.0)  # Eq.28a'
)

# Bug 6: Overwintering DC formula
# Should be log(800/qs), not log(qs/800)
code = code.replace(
    'math.log(qs / 800.0)  # Spring DC',
    'math.log(800.0 / qs)  # Spring DC'
)

with open('/app/fwi_calculator.py', 'w') as f:
    f.write(code)

print("All 6 bugs fixed in /app/fwi_calculator.py")
