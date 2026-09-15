#!/usr/bin/env python3
"""
MARS - Memory Array Redcode Simulator (ICWS'94)
A partially-implemented Core War simulator.

KNOWN ISSUES (for the solver to find and fix):
- Several opcodes have incorrect modifier handling
- Addressing mode evaluation has bugs
- Process queue management may be wrong
- Battle result counting needs work
"""

import sys
import argparse
import re
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Tuple

class Opcode(IntEnum):
    DAT = 0; MOV = 1; ADD = 2; SUB = 3; MUL = 4; DIV = 5; MOD = 6
    JMP = 7; JMZ = 8; JMN = 9; DJN = 10; CMP = 11; SNE = 12
    SLT = 13; SPL = 14; NOP = 15

class Modifier(IntEnum):
    A = 0; B = 1; AB = 2; BA = 3; F = 4; X = 5; I = 6

class Mode(IntEnum):
    IMMEDIATE = 0; DIRECT = 1; A_INDIRECT = 2; B_INDIRECT = 3
    A_DECREMENT = 4; B_DECREMENT = 5; A_INCREMENT = 6; B_INCREMENT = 7

MODE_CHARS = {'#': Mode.IMMEDIATE, '$': Mode.DIRECT, '*': Mode.A_INDIRECT,
              '@': Mode.B_INDIRECT, '{': Mode.A_DECREMENT, '<': Mode.B_DECREMENT,
              '}': Mode.A_INCREMENT, '>': Mode.B_INCREMENT}

MODE_TO_CHAR = {v: k for k, v in MODE_CHARS.items()}

OPCODE_NAMES = {n.lower(): v for n, v in Opcode.__members__.items()}
OPCODE_NAMES['seq'] = Opcode.CMP
MODIFIER_NAMES = {n.lower(): v for n, v in Modifier.__members__.items()}

@dataclass
class Instruction:
    opcode: Opcode = Opcode.DAT
    modifier: Modifier = Modifier.F
    a_mode: Mode = Mode.DIRECT
    a_number: int = 0
    b_mode: Mode = Mode.DIRECT
    b_number: int = 0

    def copy(self):
        return Instruction(self.opcode, self.modifier, self.a_mode,
                           self.a_number, self.b_mode, self.b_number)

    def __eq__(self, other):
        return (self.opcode == other.opcode and self.modifier == other.modifier and
                self.a_mode == other.a_mode and self.a_number == other.a_number and
                self.b_mode == other.b_mode and self.b_number == other.b_number)


def fold(pointer, limit, M):
    """Fold a pointer into read/write range."""
    result = pointer % limit
    if result > limit // 2:
        result += M - limit
    return result


def parse_load_file(filename, M):
    """Parse an ICWS'94 load file and return (instructions, start_offset)."""
    instructions = []
    start_offset = 0

    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(';'):
                continue

            # Handle ORG pseudo-instruction
            if line.upper().startswith('ORG'):
                parts = line.split()
                if len(parts) >= 2:
                    start_offset = int(parts[1])
                continue

            # Parse instruction: OPCODE.MODIFIER MODE_A NUMBER_A, MODE_B NUMBER_B
            # Strip inline comments
            if ';' in line:
                line = line[:line.index(';')].strip()

            m = re.match(
                r'([A-Za-z]+)\.([A-Za-z]+)\s+'
                r'([#$*@{<}>]?)\s*(-?\d+)\s*,\s*'
                r'([#$*@{<}>]?)\s*(-?\d+)',
                line
            )
            if not m:
                continue

            op_str, mod_str, a_mode_str, a_num_str, b_mode_str, b_num_str = m.groups()

            opcode = OPCODE_NAMES.get(op_str.lower())
            modifier = MODIFIER_NAMES.get(mod_str.lower())
            if opcode is None or modifier is None:
                continue

            a_mode = MODE_CHARS.get(a_mode_str, Mode.DIRECT)
            b_mode = MODE_CHARS.get(b_mode_str, Mode.DIRECT)
            a_number = int(a_num_str) % M
            b_number = int(b_num_str) % M

            instructions.append(Instruction(opcode, modifier, a_mode, a_number,
                                            b_mode, b_number))

    return instructions, start_offset


class MARS:
    def __init__(self, core_size=8000, max_processes=8000, max_cycles=80000):
        self.M = core_size
        self.max_processes = max_processes
        self.max_cycles = max_cycles
        self.core = [Instruction() for _ in range(self.M)]
        self.queues = []  # List of deques, one per warrior
        self.n_warriors = 0

    def load_warrior(self, instructions, start_offset, position):
        """Load a warrior into core at the given position."""
        for i, inst in enumerate(instructions):
            self.core[(position + i) % self.M] = inst.copy()
        queue = deque()
        queue.append((position + start_offset) % self.M)
        self.queues.append(queue)
        self.n_warriors += 1

    def reset(self):
        """Reset core to initial state."""
        self.core = [Instruction() for _ in range(self.M)]
        self.queues = []
        self.n_warriors = 0

    def execute_one(self, warrior_id):
        """Execute one instruction for the given warrior.
        Returns True if the warrior is still alive."""
        queue = self.queues[warrior_id]
        if not queue:
            return False

        PC = queue.popleft()
        M = self.M
        IR = self.core[PC].copy()

        # === Evaluate A-operand ===
        if IR.a_mode == Mode.IMMEDIATE:
            RPA = WPA = 0
        else:
            RPA = fold(IR.a_number, M, M)  # BUG: should use ReadLimit
            WPA = fold(IR.a_number, M, M)  # BUG: should use WriteLimit

            # A-number indirect modes
            if IR.a_mode in (Mode.A_INDIRECT, Mode.A_DECREMENT, Mode.A_INCREMENT):
                if IR.a_mode == Mode.A_DECREMENT:
                    self.core[(PC + WPA) % M].a_number = \
                        (self.core[(PC + WPA) % M].a_number + M - 1) % M

                PIP_A = None
                if IR.a_mode == Mode.A_INCREMENT:
                    PIP_A = (PC + WPA) % M

                RPA = fold(RPA + self.core[(PC + RPA) % M].a_number, M, M)
                WPA = fold(WPA + self.core[(PC + WPA) % M].a_number, M, M)

            # B-number indirect modes
            elif IR.a_mode in (Mode.B_INDIRECT, Mode.B_DECREMENT, Mode.B_INCREMENT):
                if IR.a_mode == Mode.B_DECREMENT:
                    self.core[(PC + WPA) % M].b_number = \
                        (self.core[(PC + WPA) % M].b_number + M - 1) % M

                PIP_A = None
                if IR.a_mode == Mode.B_INCREMENT:
                    PIP_A = (PC + WPA) % M

                RPA = fold(RPA + self.core[(PC + RPA) % M].b_number, M, M)
                WPA = fold(WPA + self.core[(PC + WPA) % M].b_number, M, M)
            else:
                PIP_A = None

        # Copy A-instruction
        IRA = self.core[(PC + RPA) % M].copy()

        # Post-increment for A-operand
        if IR.a_mode == Mode.A_INCREMENT and PIP_A is not None:
            self.core[PIP_A].a_number = (self.core[PIP_A].a_number + 1) % M
        elif IR.a_mode == Mode.B_INCREMENT and PIP_A is not None:
            self.core[PIP_A].b_number = (self.core[PIP_A].b_number + 1) % M

        # === Evaluate B-operand ===
        if IR.b_mode == Mode.IMMEDIATE:
            RPB = WPB = 0
        else:
            RPB = fold(IR.b_number, M, M)
            WPB = fold(IR.b_number, M, M)

            if IR.b_mode in (Mode.A_INDIRECT, Mode.A_DECREMENT, Mode.A_INCREMENT):
                if IR.b_mode == Mode.A_DECREMENT:
                    self.core[(PC + WPB) % M].a_number = \
                        (self.core[(PC + WPB) % M].a_number + M - 1) % M

                PIP_B = None
                if IR.b_mode == Mode.A_INCREMENT:
                    PIP_B = (PC + WPB) % M

                RPB = fold(RPB + self.core[(PC + RPB) % M].a_number, M, M)
                WPB = fold(WPB + self.core[(PC + WPB) % M].a_number, M, M)

            elif IR.b_mode in (Mode.B_INDIRECT, Mode.B_DECREMENT, Mode.B_INCREMENT):
                if IR.b_mode == Mode.B_DECREMENT:
                    self.core[(PC + WPB) % M].b_number = \
                        (self.core[(PC + WPB) % M].b_number + M - 1) % M

                PIP_B = None
                if IR.b_mode == Mode.B_INCREMENT:
                    PIP_B = (PC + WPB) % M

                RPB = fold(RPB + self.core[(PC + RPB) % M].b_number, M, M)
                WPB = fold(WPB + self.core[(PC + WPB) % M].b_number, M, M)
            else:
                PIP_B = None

        # Copy B-instruction
        IRB = self.core[(PC + RPB) % M].copy()

        # Post-increment for B-operand
        if IR.b_mode == Mode.A_INCREMENT and PIP_B is not None:
            self.core[PIP_B].a_number = (self.core[PIP_B].a_number + 1) % M
        elif IR.b_mode == Mode.B_INCREMENT and PIP_B is not None:
            self.core[PIP_B].b_number = (self.core[PIP_B].b_number + 1) % M

        # === Execute instruction ===
        op = IR.opcode
        mod = IR.modifier

        if op == Opcode.DAT:
            # Process dies - do not queue
            return len(queue) > 0

        elif op == Opcode.MOV:
            target = (PC + WPB) % M
            if mod == Modifier.A:
                self.core[target].a_number = IRA.a_number
            elif mod == Modifier.B:
                self.core[target].b_number = IRA.b_number
            elif mod == Modifier.AB:
                self.core[target].b_number = IRA.a_number
            elif mod == Modifier.BA:
                self.core[target].a_number = IRA.b_number
            elif mod == Modifier.F:
                self.core[target].a_number = IRA.a_number
                self.core[target].b_number = IRA.b_number
            elif mod == Modifier.X:
                self.core[target].b_number = IRA.a_number
                self.core[target].a_number = IRA.b_number
            elif mod == Modifier.I:
                self.core[target] = IRA.copy()
            queue.append((PC + 1) % M)

        elif op in (Opcode.ADD, Opcode.SUB, Opcode.MUL):
            target = (PC + WPB) % M
            if op == Opcode.ADD:
                func = lambda a, b: (a + b) % M
            elif op == Opcode.SUB:
                func = lambda a, b: (b + M - a) % M  # BUG: operand order wrong for some modifiers
            else:
                func = lambda a, b: (a * b) % M

            if mod == Modifier.A:
                self.core[target].a_number = func(IRA.a_number, IRB.a_number)
            elif mod == Modifier.B:
                self.core[target].b_number = func(IRA.b_number, IRB.b_number)
            elif mod == Modifier.AB:
                # BUG: uses wrong source/dest fields
                self.core[target].b_number = func(IRA.a_number, IRB.a_number)
            elif mod == Modifier.BA:
                self.core[target].a_number = func(IRA.b_number, IRB.b_number)
            elif mod in (Modifier.F, Modifier.I):
                self.core[target].a_number = func(IRA.a_number, IRB.a_number)
                self.core[target].b_number = func(IRA.b_number, IRB.b_number)
            elif mod == Modifier.X:
                self.core[target].b_number = func(IRA.a_number, IRB.a_number)
                self.core[target].a_number = func(IRA.b_number, IRB.b_number)
            queue.append((PC + 1) % M)

        elif op in (Opcode.DIV, Opcode.MOD):
            target = (PC + WPB) % M
            died = False
            if op == Opcode.DIV:
                def divop(a, b):
                    if a == 0:
                        return None
                    return b // a
            else:
                def divop(a, b):
                    if a == 0:
                        return None
                    return b % a

            if mod == Modifier.A:
                r = divop(IRA.a_number, IRB.a_number)
                if r is None:
                    died = True
                else:
                    self.core[target].a_number = r
            elif mod == Modifier.B:
                r = divop(IRA.b_number, IRB.b_number)
                if r is None:
                    died = True
                else:
                    self.core[target].b_number = r
            elif mod == Modifier.AB:
                r = divop(IRA.a_number, IRB.b_number)
                if r is None:
                    died = True
                else:
                    self.core[target].b_number = r
            elif mod == Modifier.BA:
                r = divop(IRA.b_number, IRB.a_number)
                if r is None:
                    died = True
                else:
                    self.core[target].a_number = r
            elif mod in (Modifier.F, Modifier.I):
                # BUG: doesn't handle partial division correctly
                # When one component is zero, the other should still execute
                r1 = divop(IRA.a_number, IRB.a_number)
                r2 = divop(IRA.b_number, IRB.b_number)
                if r1 is None and r2 is None:
                    died = True
                elif r1 is None:
                    self.core[target].b_number = r2
                    died = True
                elif r2 is None:
                    self.core[target].a_number = r1
                    died = True
                else:
                    self.core[target].a_number = r1
                    self.core[target].b_number = r2
            elif mod == Modifier.X:
                # BUG: X modifier crosses fields but this doesn't
                r1 = divop(IRA.a_number, IRB.a_number)
                r2 = divop(IRA.b_number, IRB.b_number)
                if r1 is None and r2 is None:
                    died = True
                elif r1 is None:
                    self.core[target].b_number = r2
                    died = True
                elif r2 is None:
                    self.core[target].a_number = r1
                    died = True
                else:
                    self.core[target].a_number = r1
                    self.core[target].b_number = r2

            if died:
                return len(queue) > 0
            queue.append((PC + 1) % M)

        elif op == Opcode.JMP:
            queue.append((PC + RPA) % M)

        elif op == Opcode.JMZ:
            if mod in (Modifier.A, Modifier.BA):
                if IRB.a_number == 0:
                    queue.append((PC + RPA) % M)
                else:
                    queue.append((PC + 1) % M)
            elif mod in (Modifier.B, Modifier.AB):
                if IRB.b_number == 0:
                    queue.append((PC + RPA) % M)
                else:
                    queue.append((PC + 1) % M)
            elif mod in (Modifier.F, Modifier.X, Modifier.I):
                if IRB.a_number == 0 and IRB.b_number == 0:
                    queue.append((PC + RPA) % M)
                else:
                    queue.append((PC + 1) % M)

        elif op == Opcode.JMN:
            if mod in (Modifier.A, Modifier.BA):
                if IRB.a_number != 0:
                    queue.append((PC + RPA) % M)
                else:
                    queue.append((PC + 1) % M)
            elif mod in (Modifier.B, Modifier.AB):
                if IRB.b_number != 0:
                    queue.append((PC + RPA) % M)
                else:
                    queue.append((PC + 1) % M)
            elif mod in (Modifier.F, Modifier.X, Modifier.I):
                # BUG: should jump if EITHER is non-zero, not BOTH
                if IRB.a_number != 0 and IRB.b_number != 0:
                    queue.append((PC + RPA) % M)
                else:
                    queue.append((PC + 1) % M)

        elif op == Opcode.DJN:
            target = (PC + WPB) % M
            if mod in (Modifier.A, Modifier.BA):
                self.core[target].a_number = (self.core[target].a_number + M - 1) % M
                IRB.a_number -= 1
                if IRB.a_number != 0:
                    queue.append((PC + RPA) % M)
                else:
                    queue.append((PC + 1) % M)
            elif mod in (Modifier.B, Modifier.AB):
                self.core[target].b_number = (self.core[target].b_number + M - 1) % M
                IRB.b_number -= 1
                if IRB.b_number != 0:
                    queue.append((PC + RPA) % M)
                else:
                    queue.append((PC + 1) % M)
            elif mod in (Modifier.F, Modifier.X, Modifier.I):
                self.core[target].a_number = (self.core[target].a_number + M - 1) % M
                IRB.a_number -= 1
                self.core[target].b_number = (self.core[target].b_number + M - 1) % M
                IRB.b_number -= 1
                # BUG: should jump if EITHER is non-zero
                if IRB.a_number != 0 and IRB.b_number != 0:
                    queue.append((PC + RPA) % M)
                else:
                    queue.append((PC + 1) % M)

        elif op == Opcode.CMP:  # SEQ
            skip = False
            if mod == Modifier.A:
                skip = IRA.a_number == IRB.a_number
            elif mod == Modifier.B:
                skip = IRA.b_number == IRB.b_number
            elif mod == Modifier.AB:
                skip = IRA.a_number == IRB.b_number
            elif mod == Modifier.BA:
                skip = IRA.b_number == IRB.a_number
            elif mod == Modifier.F:
                skip = (IRA.a_number == IRB.a_number and
                        IRA.b_number == IRB.b_number)
            elif mod == Modifier.X:
                skip = (IRA.a_number == IRB.b_number and
                        IRA.b_number == IRB.a_number)
            elif mod == Modifier.I:
                skip = (IRA == IRB)

            if skip:
                queue.append((PC + 2) % M)
            else:
                queue.append((PC + 1) % M)

        elif op == Opcode.SNE:
            skip = False
            if mod == Modifier.A:
                skip = IRA.a_number != IRB.a_number
            elif mod == Modifier.B:
                skip = IRA.b_number != IRB.b_number
            elif mod == Modifier.AB:
                skip = IRA.a_number != IRB.b_number
            elif mod == Modifier.BA:
                skip = IRA.b_number != IRB.a_number
            elif mod == Modifier.F:
                skip = (IRA.a_number != IRB.a_number or
                        IRA.b_number != IRB.b_number)
            elif mod == Modifier.X:
                skip = (IRA.a_number != IRB.b_number or
                        IRA.b_number != IRB.a_number)
            elif mod == Modifier.I:
                skip = not (IRA == IRB)

            if skip:
                queue.append((PC + 2) % M)
            else:
                queue.append((PC + 1) % M)

        elif op == Opcode.SLT:
            skip = False
            if mod == Modifier.A:
                skip = IRA.a_number < IRB.a_number
            elif mod == Modifier.B:
                skip = IRA.b_number < IRB.b_number
            elif mod == Modifier.AB:
                skip = IRA.a_number < IRB.b_number
            elif mod == Modifier.BA:
                skip = IRA.b_number < IRB.a_number
            elif mod in (Modifier.F, Modifier.I):
                skip = (IRA.a_number < IRB.a_number and
                        IRA.b_number < IRB.b_number)
            elif mod == Modifier.X:
                skip = (IRA.a_number < IRB.b_number and
                        IRA.b_number < IRB.a_number)

            if skip:
                queue.append((PC + 2) % M)
            else:
                queue.append((PC + 1) % M)

        elif op == Opcode.SPL:
            # BUG: queues in wrong order - should queue PC+1 first, then target
            queue.append((PC + RPA) % M)
            if len(queue) < self.max_processes:
                queue.append((PC + 1) % M)

        elif op == Opcode.NOP:
            queue.append((PC + 1) % M)

        return len(queue) > 0

    def run_battle(self):
        """Run a single battle. Returns index of winner or -1 for tie."""
        for cycle in range(self.max_cycles):
            for w in range(self.n_warriors):
                if self.queues[w]:
                    alive = self.execute_one(w)
                    if not alive:
                        # Check if only one warrior remains
                        living = [i for i in range(self.n_warriors) if self.queues[i]]
                        if len(living) == 1:
                            return living[0]
                        elif len(living) == 0:
                            return -1
        return -1  # Tie


def run_match(args):
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', type=int, default=8000, help='Core size')
    parser.add_argument('-p', type=int, default=8000, help='Max processes')
    parser.add_argument('-c', type=int, default=80000, help='Max cycles')
    parser.add_argument('-r', type=int, default=1, help='Rounds')
    parser.add_argument('-F', type=int, default=0, help='Fixed position (0=random)')
    parser.add_argument('warriors', nargs='+', help='Warrior load files')
    opts = parser.parse_args(args)

    M = opts.s
    w1_insts, w1_start = parse_load_file(opts.warriors[0], M)
    w2_insts, w2_start = parse_load_file(opts.warriors[1], M)

    w1_wins = 0
    w2_wins = 0
    ties = 0

    # Fixed starting position for determinism
    if opts.F > 0:
        sep = opts.F
    else:
        sep = M // 2

    for _ in range(opts.r):
        mars = MARS(M, opts.p, opts.c)
        mars.load_warrior(w1_insts, w1_start, 0)
        mars.load_warrior(w2_insts, w2_start, sep)
        result = mars.run_battle()
        if result == 0:
            w1_wins += 1
        elif result == 1:
            w2_wins += 1
        else:
            ties += 1

    print(f"{w1_wins} {w2_wins} {ties}")


if __name__ == '__main__':
    run_match(sys.argv[1:])
