#!/usr/bin/env python3
"""Compare two Hack binary files or disassemble a single file.

Usage:
  hack_diff.py <file1.hack> <file2.hack>        Compare two binaries
  hack_diff.py <file.hack> --disasm              Disassemble a single file
  hack_diff.py <file1.hack> <file2.hack> --context N   Show N lines of context around diffs
"""
import sys
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


def decode(bits_str):
    val = int(bits_str, 2)
    if not (val & 0x8000):
        return f'@{val & 0x7FFF}'
    a_comp = (val >> 6) & 0x7F
    dest = (val >> 3) & 7
    jump = val & 7
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


def read_hack(path):
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


def disassemble(path):
    lines = read_hack(path)
    print(f'Disassembly of {path} ({len(lines)} instructions):')
    print(f'{"ROM":>4s}  {"Binary":16s}  Assembly')
    print(f'{"-"*4}  {"-"*16}  {"-"*20}')
    for i, bits in enumerate(lines):
        asm = decode(bits)
        print(f'{i:4d}  {bits}  {asm}')


def diff_files(path1, path2, context=0):
    lines1 = read_hack(path1)
    lines2 = read_hack(path2)
    max_len = max(len(lines1), len(lines2))

    diff_indices = []
    for i in range(max_len):
        b1 = lines1[i] if i < len(lines1) else None
        b2 = lines2[i] if i < len(lines2) else None
        if b1 != b2:
            diff_indices.append(i)

    if not diff_indices:
        print(f'Files are identical ({len(lines1)} instructions).')
        return

    show_lines = set()
    for idx in diff_indices:
        for c in range(max(0, idx - context), min(max_len, idx + context + 1)):
            show_lines.add(c)

    print(f'Comparing {path1} ({len(lines1)} instr) vs {path2} ({len(lines2)} instr)')
    print(f'{len(diff_indices)} difference(s) found:')
    print()

    last_shown = -2
    for i in sorted(show_lines):
        if i > last_shown + 1:
            print('  ...')
        b1 = lines1[i] if i < len(lines1) else '(missing)'
        b2 = lines2[i] if i < len(lines2) else '(missing)'
        a1 = decode(b1) if b1 != '(missing)' else '(missing)'
        a2 = decode(b2) if b2 != '(missing)' else '(missing)'
        marker = '>>>' if i in diff_indices else '   '
        if i in diff_indices:
            print(f'{marker} Line {i:4d}:')
            print(f'       {path1}: {b1}  {a1}')
            print(f'       {path2}: {b2}  {a2}')
        else:
            print(f'    Line {i:4d}: {b1}  {a1}')
        last_shown = i

    print()
    print(f'Summary: {len(diff_indices)} of {max_len} lines differ.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Hack binary diff / disassembler')
    parser.add_argument('file1', help='First .hack file (or only file for --disasm)')
    parser.add_argument('file2', nargs='?', default=None,
                        help='Second .hack file (for diff mode)')
    parser.add_argument('--disasm', action='store_true',
                        help='Disassemble a single file instead of comparing')
    parser.add_argument('--context', type=int, default=2,
                        help='Lines of context around each diff (default: 2)')
    args = parser.parse_args()

    if args.disasm or args.file2 is None:
        disassemble(args.file1)
    else:
        diff_files(args.file1, args.file2, context=args.context)
