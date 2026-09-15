#!/usr/bin/env python3
"""Test runner for the 4-bit ALU design."""


import sys
sys.path.insert(0, '/app')
from hdl import Wire, Bus, simulate, bus_to_int, int_to_input_map
from design import build_alu

Wire.reset()
opcode = Bus.input(3, "op")
a = Bus.input(4, "a")
b = Bus.input(4, "b")
result = build_alu(opcode, a, b)

MASK = 0xF
OPS = ['ADD', 'SUB', 'AND', 'OR', 'XOR', 'NOT', 'SHL', 'SHR']
stats = {n: {'pass': 0, 'fail': 0, 'examples': []} for n in OPS}

for op in range(8):
    for av in range(16):
        for bv in range(16):
            inp = {}
            inp.update(int_to_input_map(opcode, op))
            inp.update(int_to_input_map(a, av))
            inp.update(int_to_input_map(b, bv))
            got = bus_to_int(simulate(result, inp))
            if   op == 0: exp = (av + bv) & MASK
            elif op == 1: exp = (av - bv) & MASK
            elif op == 2: exp = av & bv
            elif op == 3: exp = av | bv
            elif op == 4: exp = av ^ bv
            elif op == 5: exp = (~av) & MASK
            elif op == 6: exp = (av << 1) & MASK
            elif op == 7: exp = av >> 1
            name = OPS[op]
            if got == exp:
                stats[name]['pass'] += 1
            else:
                stats[name]['fail'] += 1
                if len(stats[name]['examples']) < 3:
                    stats[name]['examples'].append(
                        f"a={av} b={bv}: expected {exp}, got {got}")

print(f"{'OP':<6} {'PASS':>6} {'FAIL':>6}")
print('-' * 22)
for n in OPS:
    s = stats[n]
    tag = 'OK' if s['fail'] == 0 else 'FAIL'
    print(f"{n:<6} {s['pass']:>6} {s['fail']:>6}  {tag}")
    for ex in s['examples']:
        print(f"       {ex}")
total_p = sum(s['pass'] for s in stats.values())
total_f = sum(s['fail'] for s in stats.values())
print('-' * 22)
print(f"{'TOTAL':<6} {total_p:>6} {total_f:>6}")
if total_f > 0:
    print(f"\n{total_f} test(s) FAILED")
else:
    print("\nALL TESTS PASSED")
sys.exit(0 if total_f == 0 else 1)
