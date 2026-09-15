#!/usr/bin/env python3
"""Create SQLite database with IEEE 754 challenge values."""
import struct
import sqlite3
import random

def d2h(d):
    """Convert double to 16-char uppercase hex of its big-endian IEEE 754 bits."""
    return format(struct.unpack('>Q', struct.pack('>d', d))[0], '016X')

random.seed(20260602)

conn = sqlite3.connect('/app/challenge.db')
c = conn.cursor()

c.execute('''CREATE TABLE ieee754_values (
    id INTEGER PRIMARY KEY,
    hex_bits TEXT NOT NULL,
    category TEXT NOT NULL,
    precision_class TEXT NOT NULL
)''')

rows = []
n = 0

def add(hex_val, cat, prec):
    global n
    n += 1
    rows.append((n, hex_val, cat, prec))

# --- Special values (5) ---
add(d2h(0.0), 'special', 'exact')
add(d2h(-0.0), 'special', 'exact')
add(d2h(float('inf')), 'special', 'exact')
add(d2h(float('-inf')), 'special', 'exact')
add(d2h(float('nan')), 'special', 'exact')

# --- Exact powers of 2 (10) ---
for v in [1.0, 2.0, 0.5, 0.25, 0.125, 4.0, 8.0, 16.0, 1024.0, 0.0625]:
    add(d2h(v), 'exact_power2', 'exact')

# --- Small integers (5) ---
for v in [-3.0, 10.0, -100.0, 1000.0, -42.0]:
    add(d2h(v), 'small_integer', 'exact')

# --- Denormals (10) ---
for h in ["0000000000000001", "8000000000000001", "000FFFFFFFFFFFFF",
          "0008000000000000", "0004000000000000", "0000000000000002",
          "0000000000000010", "0000000000000100", "0000000000001000",
          "0000000000010000"]:
    add(h, 'denormal', 'extreme')

# --- Boundary values (10) ---
for h, p in [("0010000000000000", 'extreme'),
             ("7FEFFFFFFFFFFFFF", 'extreme'),
             ("FFEFFFFFFFFFFFFF", 'extreme'),
             ("3FF0000000000001", 'approx'),
             ("3FE0000000000001", 'approx'),
             ("3FEFFFFFFFFFFFFF", 'approx'),
             ("4000000000000001", 'approx'),
             ("4340000000000000", 'exact'),
             ("4340000000000001", 'exact'),
             ("4370000000000000", 'exact')]:
    add(h, 'boundary', p)

# --- Near powers of 10 (10) ---
for v in [9.999999999999998, 10.000000000000002, 0.09999999999999999,
          99.99999999999999, 999.9999999999999, 1e-4, 1e-5, 1e7, 1e20, -1e15]:
    add(d2h(v), 'near_power10', 'approx')

# --- High precision (15) ---
for v, p in [(1.0000000000000004, 'approx'),
             (2.3e-308, 'extreme'),
             (5.5e-309, 'extreme'),
             (1.5e+308, 'extreme'),
             (1e-322, 'extreme'),
             (2.2204460492503131e-16, 'approx'),
             (5.5e-200, 'approx'),
             (2.718281828459045, 'approx'),
             (3.141592653589793, 'approx'),
             (0.3, 'approx'),
             (0.1, 'approx'),
             (0.7, 'approx'),
             (1.23e-15, 'approx'),
             (9.87e200, 'approx'),
             (1.5e-150, 'approx')]:
    add(d2h(v), 'high_precision', p)

# --- Notation crossover (10) ---
for v in [0.01, 0.001, 5.5e-5, 100.0, 1e4, 2.5e-3, 1.5e-4, 1.5e4, 9.9e-5, 1.01e10]:
    add(d2h(v), 'notation_crossover', 'approx')

# --- Multi-digit (10) ---
for v in [1.5, 6.7, 1.23, 9.87, 12.34, 123.456, 1234.5678, -3.14, 0.99, 9.9]:
    add(d2h(v), 'multi_digit', 'approx')

# --- Random values (fill to 100) ---
while n < 100:
    exp = random.randint(1, 2046)
    mantissa = random.getrandbits(52)
    sign = random.randint(0, 1)
    bits = (sign << 63) | (exp << 52) | mantissa
    add(format(bits, '016X'), 'random', 'approx')

c.executemany('INSERT INTO ieee754_values VALUES (?, ?, ?, ?)', rows)

c.execute('''CREATE VIEW category_summary AS
    SELECT category, precision_class, COUNT(*) as count
    FROM ieee754_values
    GROUP BY category, precision_class
    ORDER BY category, precision_class''')

conn.commit()
conn.close()

assert n == 100, f"Expected 100 values, got {n}"
