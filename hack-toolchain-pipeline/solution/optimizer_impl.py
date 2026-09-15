#!/usr/bin/env python3
"""
Hack Assembly Peephole Optimizer.
Implements pattern-based optimizations on Hack assembly code generated
by the VM translator to reduce instruction count while preserving
functional equivalence.
"""


def optimize_asm(lines):
    """Optimize Hack assembly by removing redundant instruction sequences.

    Applies two optimization passes iteratively until convergence:
    1. Push-Pop Elimination: removes 8-instruction push_d + pop_to_d sequences
       that appear at VM command boundaries where a push is immediately followed
       by an operation that pops.
    2. SP Dereference Optimization: replaces @SP/A=M-1 with A=A-1 when the A
       register already holds the SP value after a pop operation.
    """
    lines = [l.rstrip() for l in lines]
    prev = None
    while lines != prev:
        prev = lines[:]
        lines = _eliminate_push_pop(lines)
        lines = _optimize_sp_deref(lines)
    return lines


def _s(line):
    """Strip comments and whitespace for pattern comparison."""
    return line.split('//')[0].strip()


def _eliminate_push_pop(lines):
    """Remove push_d immediately followed by pop_to_d.

    The VM translator's push_d sequence:
        @SP / A=M / M=D / @SP / M=M+1
    writes D to the stack and increments SP.

    The pop_to_d sequence:
        @SP / AM=M-1 / D=M
    decrements SP and reads the top of stack into D.

    When these 8 instructions appear consecutively, they cancel out:
    D retains its original value and SP returns to its starting position.
    Removing all 8 is safe as long as no label appears between them
    (the exact-match requirement guarantees this).
    """
    result = []
    i = 0
    n = len(lines)
    while i < n:
        if i + 7 < n:
            chunk = [_s(lines[j]) for j in range(i, i + 8)]
            if chunk == ['@SP', 'A=M', 'M=D', '@SP', 'M=M+1',
                         '@SP', 'AM=M-1', 'D=M']:
                i += 8
                continue
        result.append(lines[i])
        i += 1
    return result


def _optimize_sp_deref(lines):
    """Replace @SP/A=M-1 with A=A-1 when preceded by pop_to_d.

    After pop_to_d (@SP / AM=M-1 / D=M), the A register holds the
    new SP value. A subsequent @SP / A=M-1 (to access the second
    operand in a binary operation) can be replaced with A=A-1 since
    A already equals SP.

    Pattern: @SP / AM=M-1 / D=M / @SP / A=M-1
    Replace last two instructions with: A=A-1
    """
    result = []
    i = 0
    n = len(lines)
    while i < n:
        if i + 4 < n:
            s = [_s(lines[j]) for j in range(i, i + 5)]
            if (s[0] == '@SP' and s[1] == 'AM=M-1' and s[2] == 'D=M'
                    and s[3] == '@SP' and s[4] == 'A=M-1'):
                result.append(lines[i])      # @SP
                result.append(lines[i + 1])  # AM=M-1
                result.append(lines[i + 2])  # D=M
                result.append('A=A-1')       # replaces @SP + A=M-1
                i += 5
                continue
        result.append(lines[i])
        i += 1
    return result
