#!/usr/bin/env python3
"""
ICWS'94 compliant MARS (Memory Array Redcode Simulator).
Implements all 16 opcodes, 7 modifiers, 8 addressing modes.
Position generation matches pMARS v0.9.5 for -f (fixed) mode.

This implementation closely follows pMARS sim.c, using individual
AA_Value/AB_Value/IR_A_value/IR_B_value tracking (rather than full
IRA/IRB instruction copies) and temp-based post-increment writes.
"""

import argparse
import os
import sys
from collections import deque
from dataclasses import dataclass


# === pMARS-compatible opcode encoding ===
PMARS_OP = {
    'MOV': 0, 'ADD': 1, 'SUB': 2, 'MUL': 3, 'DIV': 4, 'MOD': 5,
    'JMZ': 6, 'JMN': 7, 'DJN': 8, 'CMP': 9, 'SLT': 10, 'SPL': 11,
    'DAT': 12, 'JMP': 13, 'SEQ': 14, 'SNE': 15, 'NOP': 16,
    'LDP': 17, 'STP': 18,
}
PMARS_MOD = {'A': 0, 'B': 1, 'AB': 2, 'BA': 3, 'F': 4, 'X': 5, 'I': 6}
PMARS_MODE = {'#': 0, '$': 1, '@': 2, '<': 3, '>': 4, '*': 5, '{': 6, '}': 7}

# Internal opcode constants
DAT, MOV, ADD, SUB, MUL, DIV, MOD = 0, 1, 2, 3, 4, 5, 6
JMP, JMZ, JMN, DJN, CMP, SNE, SLT, SPL, NOP = 7, 8, 9, 10, 11, 12, 13, 14, 15

# Modifier constants
mA, mB, mAB, mBA, mF, mX, mI = 0, 1, 2, 3, 4, 5, 6

# Addressing modes — pMARS internal encoding:
# 0=IMMEDIATE, 1=DIRECT, 2=INDIRECT, 3=PREDECR, 4=POSTINC
# With NEW_MODES: A-field variants have bit 0x80 set (matching pMARS global.h)
IMMEDIATE = 0
DIRECT = 1
INDIRECT = 2    # @: B-indirect
PREDECR = 3     # <: B-predecrement
POSTINC = 4     # >: B-postincrement
A_INDIRECT = 0x80 | INDIRECT  # *: A-indirect  = 130
A_PREDECR = 0x80 | PREDECR    # {: A-predecrement = 131
A_POSTINC = 0x80 | POSTINC    # }: A-postincrement = 132

OPCODE_FROM_STR = {
    'DAT': DAT, 'MOV': MOV, 'ADD': ADD, 'SUB': SUB, 'MUL': MUL,
    'DIV': DIV, 'MOD': MOD, 'JMP': JMP, 'JMZ': JMZ, 'JMN': JMN,
    'DJN': DJN, 'CMP': CMP, 'SEQ': CMP, 'SNE': SNE, 'SLT': SLT,
    'SPL': SPL, 'NOP': NOP,
}
MOD_FROM_STR = {'A': mA, 'B': mB, 'AB': mAB, 'BA': mBA, 'F': mF, 'X': mX, 'I': mI}
MODE_FROM_SYM = {
    '#': IMMEDIATE, '$': DIRECT, '@': INDIRECT, '*': A_INDIRECT,
    '<': PREDECR, '>': POSTINC, '{': A_PREDECR, '}': A_POSTINC,
}


@dataclass(slots=True)
class Instruction:
    op: int
    mod: int
    am: int      # A addressing mode (pMARS internal 0-7)
    an: int      # A number
    bm: int      # B addressing mode (pMARS internal 0-7)
    bn: int      # B number
    ckop: int    # pMARS opcode index for checksum (SEQ=14 vs CMP=9)

    def copy(self):
        return Instruction(self.op, self.mod, self.am, self.an, self.bm, self.bn, self.ckop)


def make_dat():
    return Instruction(DAT, mF, DIRECT, 0, DIRECT, 0, PMARS_OP['DAT'])


@dataclass
class Warrior:
    name: str
    instructions: list
    start: int = 0


def parse_warrior(filepath: str, M: int) -> Warrior:
    name = os.path.basename(filepath)
    if name.endswith('.red'):
        name = name[:-4]
    instructions = []
    start = 0
    with open(filepath, 'r') as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(';'):
                if line.lower().startswith(';name'):
                    name = line[5:].strip()
                continue
            upper = line.upper().split(';')[0].strip()
            if upper.startswith('ORG'):
                parts = upper.split()
                if len(parts) >= 2:
                    start = int(parts[1])
                continue
            if upper.startswith('END'):
                break
            line = line.split(';')[0].strip()
            if not line:
                continue
            instr = parse_instruction(line, M)
            if instr is not None:
                instructions.append(instr)
    return Warrior(name=name, instructions=instructions, start=start)


def parse_instruction(line: str, M: int):
    parts = line.split(None, 1)
    if not parts:
        return None
    op_part = parts[0].upper()
    if '.' in op_part:
        op_str, mod_str = op_part.split('.', 1)
    else:
        op_str = op_part
        mod_str = 'F'
    if op_str not in OPCODE_FROM_STR:
        return None
    opcode = OPCODE_FROM_STR[op_str]
    modifier = MOD_FROM_STR.get(mod_str, mF)
    # Preserve pMARS opcode encoding for checksum (SEQ=14 vs CMP=9)
    ckop = PMARS_OP.get(op_str, PMARS_OP['DAT'])
    a_mode, a_number = DIRECT, 0
    b_mode, b_number = DIRECT, 0
    if len(parts) > 1:
        operand_str = parts[1].strip()
        if ',' in operand_str:
            a_str, b_str = operand_str.split(',', 1)
        else:
            a_str = operand_str
            b_str = ''
        a_mode, a_number = parse_operand(a_str.strip(), M)
        if b_str.strip():
            b_mode, b_number = parse_operand(b_str.strip(), M)
    return Instruction(opcode, modifier, a_mode, a_number, b_mode, b_number, ckop)


def parse_operand(s: str, M: int):
    s = s.strip()
    if not s:
        return DIRECT, 0
    mode = DIRECT
    if s[0] in MODE_FROM_SYM:
        mode = MODE_FROM_SYM[s[0]]
        s = s[1:].strip()
    try:
        val = int(s) % M
    except ValueError:
        val = 0
    return mode, val


# === pMARS-compatible RNG ===

def pmars_rng(seed: int) -> int:
    temp = seed
    q = int(temp / 127773)
    r = temp - q * 127773
    temp = 16807 * r - 2836 * q
    if temp < 0:
        temp += 2147483647
    return temp


def checksum_warriors(warriors: list, M: int) -> int:
    """Compute pMARS-compatible checksum from warrior instructions."""
    shuffle = 0
    checksum = 0
    for w in warriors:
        for instr in w.instructions:
            pmars_combined = (instr.ckop << 3) + instr.mod
            checksum += pmars_combined ^ shuffle; shuffle += 1
            checksum += instr.am ^ shuffle; shuffle += 1
            checksum += instr.bm ^ shuffle; shuffle += 1
            checksum += instr.an ^ shuffle; shuffle += 1
            checksum += instr.bn ^ shuffle; shuffle += 1
    checksum = checksum & 0xFFFFFFFF
    if checksum >= 0x80000000:
        checksum -= 0x100000000
    return checksum


def is_indir_a(mode):
    """Check if mode is an A-field indirect variant (*, {, }). Bit 0x80 set."""
    return bool(mode & 0x80)

def raw_mode(mode):
    """Convert extended A-indirect mode to base mode. Clear bit 0x80."""
    return mode & 0x7F


class MARS:
    def __init__(self, core_size=8000, max_cycles=80000, max_processes=8000,
                 max_length=100, min_distance=100):
        self.M = core_size
        self.max_cycles = max_cycles
        self.max_processes = max_processes
        self.max_length = max_length
        self.min_distance = min_distance
        self.core = None

    def init_core(self):
        self.core = [make_dat() for _ in range(self.M)]

    def load_warrior(self, warrior: Warrior, position: int) -> deque:
        for i, instr in enumerate(warrior.instructions):
            self.core[(position + i) % self.M] = instr.copy()
        q = deque()
        q.append((position + warrior.start) % self.M)
        return q

    def execute(self, pc: int, queue: deque) -> bool:
        """Execute one instruction. Returns True if task survives.

        Closely follows pMARS sim.c: tracks individual register values
        (AA_Value, IR.A_value, AB_Value, IR.B_value), uses saved temp
        values for post-increment writes, and MOV.I copies from current
        memory then overrides with snapshot values."""
        M = self.M
        M1 = M - 1
        core = self.core

        # Step 2: Copy instruction register
        ir = core[pc]
        ir_op = ir.op
        ir_mod = ir.mod
        ir_am = ir.am
        ir_an = ir.an
        ir_bm = ir.bm
        ir_bn = ir.bn

        # ============================================================
        # A-operand evaluation (Steps 3-4)
        # ============================================================

        if ir_am == IMMEDIATE:
            addrA = pc
            aa_val = ir_an
            ira_bval = ir_bn
        elif ir_am == DIRECT:
            addrA = (pc + ir_an) % M
            c = core[addrA]
            aa_val = c.an
            ira_bval = c.bn
        else:
            # Indirect mode (modes 2-7)
            base_mode = ir_am
            use_a_field = False
            if is_indir_a(ir_am):
                base_mode = raw_mode(ir_am)
                use_a_field = True

            inter_a = (pc + ir_an) % M
            inter_cell = core[inter_a]

            if use_a_field:
                temp_a = inter_cell.an
            else:
                temp_a = inter_cell.bn

            # Pre-decrement
            if base_mode == PREDECR:
                temp_a = (temp_a + M1) % M
                if use_a_field:
                    inter_cell.an = temp_a
                else:
                    inter_cell.bn = temp_a

            # Compute final A address
            addrA = (inter_a + temp_a) % M
            c = core[addrA]
            aa_val = c.an
            ira_bval = c.bn

            # Post-increment (Step 4) — uses saved temp_a like pMARS
            if base_mode == POSTINC:
                temp_a = (temp_a + 1) % M
                if use_a_field:
                    inter_cell.an = temp_a
                else:
                    inter_cell.bn = temp_a

        # ============================================================
        # B-operand evaluation (Steps 5-6)
        # ============================================================

        if ir_bm == IMMEDIATE:
            addrB = pc
            ab_val = core[pc].an
            irb_bval = core[pc].bn
        elif ir_bm == DIRECT:
            addrB = (pc + ir_bn) % M
            c = core[addrB]
            ab_val = c.an
            irb_bval = c.bn
        else:
            base_mode = ir_bm
            use_a_field = False
            if is_indir_a(ir_bm):
                base_mode = raw_mode(ir_bm)
                use_a_field = True

            inter_b = (pc + ir_bn) % M
            inter_cell = core[inter_b]

            if use_a_field:
                temp_b = inter_cell.an
            else:
                temp_b = inter_cell.bn

            if base_mode == PREDECR:
                temp_b = (temp_b + M1) % M
                if use_a_field:
                    inter_cell.an = temp_b
                else:
                    inter_cell.bn = temp_b

            addrB = (inter_b + temp_b) % M
            c = core[addrB]
            ab_val = c.an
            irb_bval = c.bn

            if base_mode == POSTINC:
                temp_b = (temp_b + 1) % M
                if use_a_field:
                    inter_cell.an = temp_b
                else:
                    inter_cell.bn = temp_b

        # ============================================================
        # Execute (Step 7)
        # ============================================================

        target = core[addrB]

        if ir_op == DAT:
            return False

        elif ir_op == MOV:
            if ir_mod == mA:
                target.an = aa_val
            elif ir_mod == mB:
                target.bn = ira_bval
            elif ir_mod == mAB:
                target.bn = aa_val
            elif ir_mod == mBA:
                target.an = ira_bval
            elif ir_mod == mF:
                target.an = aa_val
                target.bn = ira_bval
            elif ir_mod == mX:
                target.an = ira_bval
                target.bn = aa_val
            elif ir_mod == mI:
                # pMARS: copy whole instruction from current memory[addrA],
                # then override A_value and B_value with snapshot values
                core[addrB] = core[addrA].copy()
                core[addrB].an = aa_val
                core[addrB].bn = ira_bval
            queue.append((pc + 1) % M)

        elif ir_op in (ADD, SUB, MUL):
            def arith_a(src, dst):
                if ir_op == ADD: return (src + dst) % M
                elif ir_op == SUB: return (dst - src + M) % M
                else: return (src * dst) % M

            if ir_mod == mA:
                target.an = arith_a(aa_val, ab_val)
            elif ir_mod == mB:
                target.bn = arith_a(ira_bval, irb_bval)
            elif ir_mod == mAB:
                target.bn = arith_a(aa_val, irb_bval)
            elif ir_mod == mBA:
                target.an = arith_a(ira_bval, ab_val)
            elif ir_mod in (mF, mI):
                target.an = arith_a(aa_val, ab_val)
                target.bn = arith_a(ira_bval, irb_bval)
            elif ir_mod == mX:
                target.an = arith_a(ira_bval, ab_val)
                target.bn = arith_a(aa_val, irb_bval)
            queue.append((pc + 1) % M)

        elif ir_op in (DIV, MOD):
            is_div = (ir_op == DIV)
            def dm(a, b):
                if a == 0:
                    return None
                return b // a if is_div else b % a

            died = False
            if ir_mod == mA:
                r = dm(aa_val, ab_val)
                if r is None: died = True
                else: target.an = r
            elif ir_mod == mB:
                r = dm(ira_bval, irb_bval)
                if r is None: died = True
                else: target.bn = r
            elif ir_mod == mAB:
                r = dm(aa_val, irb_bval)
                if r is None: died = True
                else: target.bn = r
            elif ir_mod == mBA:
                r = dm(ira_bval, ab_val)
                if r is None: died = True
                else: target.an = r
            elif ir_mod in (mF, mI):
                ra = dm(aa_val, ab_val)
                rb = dm(ira_bval, irb_bval)
                if ra is not None:
                    target.an = ra
                    if rb is not None:
                        target.bn = rb
                    else:
                        died = True
                else:
                    if rb is not None:
                        target.bn = rb
                    died = True
            elif ir_mod == mX:
                ra = dm(ira_bval, ab_val)
                rb = dm(aa_val, irb_bval)
                if ra is not None:
                    target.an = ra
                    if rb is not None:
                        target.bn = rb
                    else:
                        died = True
                else:
                    if rb is not None:
                        target.bn = rb
                    died = True

            if died:
                return False
            queue.append((pc + 1) % M)

        elif ir_op == JMP:
            queue.append(addrA)

        elif ir_op == JMZ:
            if ir_mod in (mA, mBA):
                jump = (ab_val == 0)
            elif ir_mod in (mB, mAB):
                jump = (irb_bval == 0)
            elif ir_mod in (mF, mX, mI):
                jump = (ab_val == 0 and irb_bval == 0)
            else:
                jump = False
            queue.append(addrA if jump else (pc + 1) % M)

        elif ir_op == JMN:
            if ir_mod in (mA, mBA):
                jump = (ab_val != 0)
            elif ir_mod in (mB, mAB):
                jump = (irb_bval != 0)
            elif ir_mod in (mF, mX, mI):
                jump = (ab_val != 0 or irb_bval != 0)
            else:
                jump = False
            queue.append(addrA if jump else (pc + 1) % M)

        elif ir_op == DJN:
            # pMARS with NEW_MODES: decrement target, test original snapshot
            if ir_mod in (mA, mBA):
                target.an = (target.an + M1) % M
                jump = (ab_val != 1)
            elif ir_mod in (mB, mAB):
                target.bn = (target.bn + M1) % M
                jump = (irb_bval != 1)
            elif ir_mod in (mF, mX, mI):
                target.an = (target.an + M1) % M
                target.bn = (target.bn + M1) % M
                jump = not (ab_val == 1 and irb_bval == 1)
            else:
                jump = False
            queue.append(addrA if jump else (pc + 1) % M)

        elif ir_op == CMP:  # CMP/SEQ
            if ir_mod == mA:
                eq = (aa_val == ab_val)
            elif ir_mod == mB:
                eq = (ira_bval == irb_bval)
            elif ir_mod == mAB:
                eq = (aa_val == irb_bval)
            elif ir_mod == mBA:
                eq = (ira_bval == ab_val)
            elif ir_mod == mF:
                eq = (aa_val == ab_val and ira_bval == irb_bval)
            elif ir_mod == mX:
                eq = (aa_val == irb_bval and ira_bval == ab_val)
            elif ir_mod == mI:
                ca = core[addrA]
                cb = core[addrB]
                eq = (ca.op == cb.op and ca.mod == cb.mod and
                      ca.am == cb.am and ca.bm == cb.bm and
                      aa_val == ab_val and ira_bval == irb_bval)
            else:
                eq = False
            queue.append((pc + 2) % M if eq else (pc + 1) % M)

        elif ir_op == SNE:
            if ir_mod == mA:
                ne = (aa_val != ab_val)
            elif ir_mod == mB:
                ne = (ira_bval != irb_bval)
            elif ir_mod == mAB:
                ne = (aa_val != irb_bval)
            elif ir_mod == mBA:
                ne = (ira_bval != ab_val)
            elif ir_mod == mF:
                ne = (aa_val != ab_val or ira_bval != irb_bval)
            elif ir_mod == mX:
                ne = (aa_val != irb_bval or ira_bval != ab_val)
            elif ir_mod == mI:
                ca = core[addrA]
                cb = core[addrB]
                ne = not (ca.op == cb.op and ca.mod == cb.mod and
                          ca.am == cb.am and ca.bm == cb.bm and
                          aa_val == ab_val and ira_bval == irb_bval)
            else:
                ne = False
            queue.append((pc + 2) % M if ne else (pc + 1) % M)

        elif ir_op == SLT:
            if ir_mod == mA:
                lt = (aa_val < ab_val)
            elif ir_mod == mB:
                lt = (ira_bval < irb_bval)
            elif ir_mod == mAB:
                lt = (aa_val < irb_bval)
            elif ir_mod == mBA:
                lt = (ira_bval < ab_val)
            elif ir_mod in (mF, mI):
                lt = (aa_val < ab_val and ira_bval < irb_bval)
            elif ir_mod == mX:
                lt = (aa_val < irb_bval and ira_bval < ab_val)
            else:
                lt = False
            queue.append((pc + 2) % M if lt else (pc + 1) % M)

        elif ir_op == SPL:
            queue.append((pc + 1) % M)
            if len(queue) < self.max_processes:
                queue.append(addrA)

        elif ir_op == NOP:
            queue.append((pc + 1) % M)

        return True

    def run_battle(self, warriors: list, positions: list, starter: int = 0) -> int:
        """Run one round. Returns winner index or -1 for tie."""
        self.init_core()
        n = len(warriors)
        queues = []
        for i, w in enumerate(warriors):
            q = self.load_warrior(w, positions[i])
            queues.append(q)

        alive = list(range(n))
        cycle = n * self.max_cycles
        current = starter % len(alive)

        while cycle > 0 and len(alive) > 1:
            idx = alive[current]
            q = queues[idx]

            if q:
                pc = q.popleft()
                self.execute(pc, q)

            if not q:
                wl = len(alive)
                cycle = cycle - 1 - (cycle - 1) // wl
                alive.remove(idx)
                if not alive:
                    break
                if current >= len(alive):
                    current = 0
            else:
                cycle -= 1
                current = (current + 1) % len(alive)

        if len(alive) == 1:
            return alive[0]
        return -1


def run_rounds(mars: MARS, warriors: list, rounds: int, fixed: bool) -> list:
    n = len(warriors)
    wins = [0] * n
    losses = [0] * n
    ties = [0] * n

    separation = mars.min_distance
    if separation < mars.max_length:
        separation = mars.max_length

    if fixed:
        seed = pmars_rng(checksum_warriors(warriors, mars.M))
    else:
        import time
        seed = pmars_rng(int(time.time()))

    positions_range = mars.M + 1 - 2 * separation

    for r in range(rounds):
        if n == 2:
            pos = [0, separation + (seed % positions_range)]
            seed = pmars_rng(seed)
        else:
            pos = [0]
            for i in range(1, n):
                p = separation + (seed % positions_range)
                pos.append(p)
                seed = pmars_rng(seed)

        starter = r % n
        winner = mars.run_battle(warriors, pos, starter)

        if winner == -1:
            for i in range(n):
                ties[i] += 1
        else:
            wins[winner] += 1
            for i in range(n):
                if i != winner:
                    losses[i] += 1

    return [(wins[i], losses[i], ties[i]) for i in range(n)]


def main():
    parser = argparse.ArgumentParser(description="ICWS'94 MARS Simulator")
    parser.add_argument('-s', type=int, default=8000, help='Core size')
    parser.add_argument('-c', type=int, default=80000, help='Max cycles')
    parser.add_argument('-p', type=int, default=8000, help='Max processes')
    parser.add_argument('-l', type=int, default=100, help='Max warrior length')
    parser.add_argument('-d', type=int, default=100, help='Min distance')
    parser.add_argument('-r', type=int, default=1, help='Number of rounds')
    parser.add_argument('-f', action='store_true', help='Fixed positioning')
    parser.add_argument('warriors', nargs='+', help='Warrior files')

    args = parser.parse_args()

    mars = MARS(
        core_size=args.s,
        max_cycles=args.c,
        max_processes=args.p,
        max_length=args.l,
        min_distance=args.d,
    )

    warriors = []
    for wf in args.warriors:
        w = parse_warrior(wf, args.s)
        warriors.append(w)

    results = run_rounds(mars, warriors, args.r, args.f)

    for i, w in enumerate(warriors):
        name = os.path.basename(args.warriors[i])
        if name.endswith('.red'):
            name = name[:-4]
        wins, losses_count, ties_count = results[i]
        print(f"{name} {wins} {losses_count} {ties_count}")


if __name__ == '__main__':
    main()
