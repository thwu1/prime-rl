#!/usr/bin/env python3
"""Deterministic trace generator for cache analysis task."""
import random
import os

def generate_trace_small(seed=42):
    random.seed(seed)
    trace = []
    for i in range(50):
        trace.append(('r', i * 64))
    for i in range(50):
        addr = random.randint(0, 9) * 64
        trace.append(('r', addr))
    for i in range(50):
        addr = random.randint(0, 4) * 64
        trace.append(('w', addr))
    for i in range(50):
        addr = (i * 3 % 20) * 64
        op = 'r' if random.random() > 0.3 else 'w'
        trace.append((op, addr))
    return trace

def generate_trace_medium(seed=123):
    random.seed(seed)
    trace = []
    for i in range(500):
        addr = random.randint(0, 7) * 64
        op = 'r' if random.random() > 0.2 else 'w'
        trace.append((op, addr))
    for i in range(500):
        addr = random.randint(0, 31) * 64
        op = 'r' if random.random() > 0.3 else 'w'
        trace.append((op, addr))
    for i in range(500):
        addr = (i * 13 % 128) * 64
        op = 'r' if i % 3 != 0 else 'w'
        trace.append((op, addr))
    for i in range(500):
        r = random.random()
        if r < 0.3:
            addr = random.randint(0, 7) * 64
        elif r < 0.6:
            addr = random.randint(0, 31) * 64
        else:
            addr = random.randint(0, 127) * 64
        op = 'r' if random.random() > 0.25 else 'w'
        trace.append((op, addr))
    return trace

def write_trace(trace, filepath):
    with open(filepath, 'w') as f:
        for op, addr in trace:
            f.write(f"{op} {addr:08x}\n")

if __name__ == '__main__':
    os.makedirs('/app/traces', exist_ok=True)
    write_trace(generate_trace_small(), '/app/traces/trace_small.txt')
    write_trace(generate_trace_medium(), '/app/traces/trace_medium.txt')
    print("Generated trace_small.txt (200 accesses) and trace_medium.txt (2000 accesses)")
