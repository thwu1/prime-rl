#!/usr/bin/env python3
"""Generate input numbers for the number parsing evaluation task."""
import random
import os

random.seed(0x46505F42554753)  # deterministic

numbers = []

# Normal-range floats
for _ in range(300):
    v = random.uniform(-1000, 1000)
    numbers.append(f"{v}")

# Integers
for _ in range(100):
    v = random.randint(-10**15, 10**15)
    numbers.append(str(v))

# Scientific notation, moderate range
for _ in range(150):
    m = random.uniform(1, 9.999)
    e = random.randint(-100, 100)
    sign = random.choice(['', '-'])
    numbers.append(f"{sign}{m:.15g}e{e}")

# Near fast-path exponent boundaries
for _ in range(50):
    m = random.uniform(0.001, 999)
    e = random.choice([-22, -21, -20, -15, -10, 22, 23, 30, 35])
    numbers.append(f"{m:.16g}e{e}")

# === IEEE 754 edge cases ===

# Negative zeros
numbers.extend([
    "-0.0", "-0e0", "-0.0e10", "-0.00", "-0e-5",
    "-0.0e-100", "-00.00", "-0e1",
])

# Subnormal values
numbers.extend([
    "5e-324",
    "4.9406564584124654e-324",
    "1e-310",
    "1e-315",
    "1e-320",
    "1e-309",
    "2.2250738585072013e-308",
    "2.2250738585072014e-308",
    "1.5e-310",
    "9.9e-321",
    "1e-323",
    "2.4703282292062328e-324",
    "1e-308",
    "2e-308",
    "1.5e-308",
])

# Normal values near subnormal boundary
numbers.extend([
    "2.2250738585072019e-308",
    "3e-308",
    "1e-307",
])

# Values with many significant digits
numbers.extend([
    "3.14159265358979323846264338327950288",
    "2.71828182845904523536028747135266250",
    "1.00000000000000000001",
    "9007199254740993.0",
    "9007199254740992.0",
    "9007199254740991.0",
])

# Zero variants
numbers.extend(["0.0", "0e0", "0", "0.0e100", "0.0e-100"])

# Large finite values
numbers.extend([
    "1e200",
    "-1e200",
    "1e150",
    "-1e150",
])

# Random digit patterns with varied exponents
for _ in range(50):
    d = random.randint(1, 20)
    digits = ''.join([str(random.randint(0, 9)) for _ in range(d)])
    while digits[0] == '0' and len(digits) > 1:
        digits = str(random.randint(1, 9)) + digits[1:]
    exp = random.randint(-200, 200)
    sign = random.choice(['', '-'])
    numbers.append(f"{sign}{digits[0]}.{digits[1:]}e{exp}" if len(digits) > 1
                   else f"{sign}{digits}e{exp}")

# Shuffle deterministically
random.shuffle(numbers)

os.makedirs('/app/data', exist_ok=True)
with open('/app/data/input.txt', 'w') as f:
    for n in numbers:
        f.write(n + '\n')

print(f"Generated {len(numbers)} test numbers")
