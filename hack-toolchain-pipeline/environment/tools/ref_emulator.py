#!/usr/bin/env python3
"""Standalone Hack CPU Emulator — reference implementation for verification.

Usage:
  ref_emulator.py <hack_file> <cycles> [init_ram_json]
  ref_emulator.py <hack_file> <cycles> [init_ram_json] --trace [--trace-limit N]
  ref_emulator.py <hack_file> <cycles> [init_ram_json] --ram-range 0-10,256-260

Options:
  --trace           Step-by-step execution trace (registers, decoded instructions, RAM writes)
  --trace-limit N   Maximum trace lines to print (default: 200)
  --ram-range R     Only display RAM addresses in given ranges (e.g. "0-10,256-260")
"""
import sys
import json
import argparse

_COMP_DECODE = {
    0b0101010: '0',   0b0111111: '1',   0b0111010: '-1',
    0b0001100: 'D',   0b0110000: 'A',   0b0001101: '!D',
    0b0110001: '!A',  0b0001111: '-D',  0b0110011: '-A',
    0b0011111: 'D+1', 0b0110111: 'A+1', 0b0001110: 'D-1',
    0b0110010: 'A-1', 0b0000010: 'D+A', 0b0010011: 'D-A',
    0b0000111: 'A-D', 0b0000000: 'D&A', 0b0010101: 'D|A',
    0b1110000: 'M',   0b1110001: '!M',  0b1110011: '-M',
    0b1110111: 'M+1', 0b1110010: 'M-1', 0b1000010: 'D+M',
    0b1010011: 'D-M', 0b1000111: 'M-D', 0b1000000: 'D&M',
    0b1010101: 'D|M',
}
_DEST_DECODE = {0: '', 1: 'M', 2: 'D', 3: 'DM', 4: 'A', 5: 'AM', 6: 'AD', 7: 'ADM'}
_JUMP_DECODE = {0: '', 1: 'JGT', 2: 'JEQ', 3: 'JGE', 4: 'JLT', 5: 'JNE', 6: 'JLE', 7: 'JMP'}


def _decode_instruction(inst):
    if not (inst & 0x8000):
        return f'@{inst & 0x7FFF}'
    a_comp = (inst >> 6) & 0x7F
    dest = (inst >> 3) & 7
    jump = inst & 7
    comp_s = _COMP_DECODE.get(a_comp, f'?{a_comp:07b}')
    dest_s = _DEST_DECODE.get(dest, '?')
    jump_s = _JUMP_DECODE.get(jump, '?')
    parts = []
    if dest_s:
        parts.append(f'{dest_s}={comp_s}')
    else:
        parts.append(comp_s)
    if jump_s:
        parts[-1] += f';{jump_s}'
    return ''.join(parts)


def _sign16(v):
    v = v & 0xFFFF
    return v - 0x10000 if v >= 0x8000 else v


def _alu(comp_bits, d_val, y_val):
    zx = (comp_bits >> 5) & 1
    nx = (comp_bits >> 4) & 1
    zy = (comp_bits >> 3) & 1
    ny = (comp_bits >> 2) & 1
    f  = (comp_bits >> 1) & 1
    no = comp_bits & 1
    x = d_val & 0xFFFF
    y = y_val & 0xFFFF
    if zx: x = 0
    if nx: x = (~x) & 0xFFFF
    if zy: y = 0
    if ny: y = (~y) & 0xFFFF
    if f:
        out = (x + y) & 0xFFFF
    else:
        out = x & y
    if no:
        out = (~out) & 0xFFFF
    return out


def emulate(hack_file, cycles, init_ram=None, trace=False, trace_limit=200):
    with open(hack_file) as f:
        rom = [int(line.strip(), 2) for line in f if line.strip()]
    ram = [0] * 32768
    if init_ram:
        for addr, val in init_ram.items():
            ram[int(addr)] = val & 0xFFFF
    a_reg = 0
    d_reg = 0
    pc = 0
    trace_count = 0
    for step in range(cycles):
        if pc >= len(rom):
            a_reg = 0
            pc += 1
            continue
        inst = rom[pc]
        do_trace = trace and trace_count < trace_limit
        if do_trace:
            decoded = _decode_instruction(inst)
            prefix = f'[{step:5d}] PC={pc:4d} A={_sign16(a_reg):6d} D={_sign16(d_reg):6d} | {decoded}'
        if not (inst & 0x8000):
            a_reg = inst & 0x7FFF
            if do_trace:
                print(f'{prefix} -> A={a_reg}')
                trace_count += 1
            pc += 1
        else:
            a_bit = (inst >> 12) & 1
            comp  = (inst >> 6) & 0x3F
            dest  = (inst >> 3) & 7
            jump  = inst & 7
            y_val = ram[a_reg & 0x7FFF] if a_bit else a_reg
            result = _alu(comp, d_reg, y_val)
            old_a = a_reg
            effects = []
            if dest & 4:
                a_reg = result
                effects.append(f'A={_sign16(result)}')
            if dest & 2:
                d_reg = result
                effects.append(f'D={_sign16(result)}')
            if dest & 1:
                ram[old_a & 0x7FFF] = result
                effects.append(f'RAM[{old_a}]={_sign16(result)}')
            s = _sign16(result)
            do_jump = False
            if jump & 4 and s < 0:
                do_jump = True
            if jump & 2 and s == 0:
                do_jump = True
            if jump & 1 and s > 0:
                do_jump = True
            if do_jump:
                effects.append(f'JUMP->{old_a}')
                pc = old_a & 0x7FFF
            else:
                pc += 1
            if do_trace:
                print(f'{prefix} -> {", ".join(effects)}')
                trace_count += 1
    if trace and trace_count >= trace_limit:
        print(f'... (trace truncated at {trace_limit} lines, ran {cycles} total cycles)')
    out = {}
    for i in range(len(ram)):
        if ram[i] != 0:
            out[i] = _sign16(ram[i])
    return out


def _parse_ranges(range_str):
    ranges = []
    for part in range_str.split(','):
        part = part.strip()
        if '-' in part:
            lo, hi = part.split('-', 1)
            ranges.append((int(lo), int(hi)))
        else:
            ranges.append((int(part), int(part)))
    return ranges


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Hack CPU Emulator (reference)')
    parser.add_argument('hack_file', help='Path to .hack binary file')
    parser.add_argument('cycles', type=int, help='Number of CPU cycles to execute')
    parser.add_argument('init_ram', nargs='?', default=None,
                        help='Initial RAM as JSON: \'{"0":256,"1":300}\'')
    parser.add_argument('--trace', action='store_true',
                        help='Enable step-by-step execution trace')
    parser.add_argument('--trace-limit', type=int, default=200,
                        help='Max trace lines to display (default: 200)')
    parser.add_argument('--ram-range', default=None,
                        help='Only show RAM in ranges, e.g. "0-10,256-260"')
    args = parser.parse_args()

    ir = json.loads(args.init_ram) if args.init_ram else None
    if ir:
        ir = {int(k): int(v) for k, v in ir.items()}

    result = emulate(args.hack_file, args.cycles, init_ram=ir,
                     trace=args.trace, trace_limit=args.trace_limit)

    if args.ram_range:
        ranges = _parse_ranges(args.ram_range)
        filtered = {}
        for addr, val in result.items():
            for lo, hi in ranges:
                if lo <= addr <= hi:
                    filtered[addr] = val
                    break
        result = filtered

    print(json.dumps({str(k): v for k, v in sorted(result.items())}, indent=2))
