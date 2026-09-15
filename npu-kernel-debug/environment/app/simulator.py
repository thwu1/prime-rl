#!/usr/bin/env python3
"""MiniNPU Transaction-Level Simulator."""

import numpy as np
import sys

VLEN = 16
NUM_VREGS = 16
NUM_SREGS = 16
MEM_SIZE = 4096


class MiniNPU:
    """Transaction-level simulator for the MiniNPU architecture."""

    def __init__(self):
        self.vregs = np.zeros((NUM_VREGS, VLEN), dtype=np.float32)
        self.sregs = np.zeros(NUM_SREGS, dtype=np.float32)
        self.memory = np.zeros(MEM_SIZE, dtype=np.float32)
        self.pc = 0
        self.halted = False
        self.labels = {}
        self.instructions = []

    def reset(self):
        """Reset all state to initial values."""
        self.vregs[:] = 0.0
        self.sregs[:] = 0.0
        self.memory[:] = 0.0
        self.pc = 0
        self.halted = False

    def load_program(self, text):
        """Parse assembly text into internal representation."""
        self.instructions = []
        self.labels = {}
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('.') and line.endswith(':'):
                label = line[1:-1].strip()
                self.labels[label] = len(self.instructions)
                continue
            self.instructions.append(line)

    def load_memory(self, addr, data):
        """Load float32 data into scratchpad starting at word address addr."""
        data = np.asarray(data, dtype=np.float32).ravel()
        self.memory[addr:addr + len(data)] = data

    def read_memory(self, addr, length):
        """Read length words from scratchpad starting at word address addr."""
        return self.memory[addr:addr + length].copy()

    def run(self, max_steps=200000):
        """Execute the loaded program. Returns number of steps executed."""
        self.pc = 0
        self.halted = False
        steps = 0
        while not self.halted and self.pc < len(self.instructions) and steps < max_steps:
            self._step()
            steps += 1
        return steps

    def _step(self):
        """Execute one instruction at current PC."""
        raw = self.instructions[self.pc]
        clean = raw.replace(',', ' ')
        parts = clean.split()
        op = parts[0].upper()

        if op == 'HALT':
            self.halted = True
            return

        elif op == 'VLD':
            vd = int(parts[1][1:])
            addr = int(parts[2])
            self.vregs[vd] = self.memory[addr:addr + VLEN].copy()

        elif op == 'VST':
            vs = int(parts[1][1:])
            addr = int(parts[2])
            self.memory[addr:addr + VLEN] = self.vregs[vs]

        elif op == 'SLD':
            sd = int(parts[1][1:])
            addr = int(parts[2])
            if sd != 0:
                self.sregs[sd] = float(self.memory[addr])

        elif op == 'SST':
            ss = int(parts[1][1:])
            addr = int(parts[2])
            self.memory[addr] = np.float32(self.sregs[ss])

        elif op == 'VADD':
            vd = int(parts[1][1:])
            vs1 = int(parts[2][1:])
            vs2 = int(parts[3][1:])
            self.vregs[vd] = self.vregs[vs1] + self.vregs[vs2]

        elif op == 'VSUB':
            vd = int(parts[1][1:])
            vs1 = int(parts[2][1:])
            vs2 = int(parts[3][1:])
            self.vregs[vd] = self.vregs[vs2] - self.vregs[vs1]

        elif op == 'VMUL':
            vd = int(parts[1][1:])
            vs1 = int(parts[2][1:])
            vs2 = int(parts[3][1:])
            self.vregs[vd] = self.vregs[vs1] * self.vregs[vs2]

        elif op == 'VDIV':
            vd = int(parts[1][1:])
            vs1 = int(parts[2][1:])
            vs2 = int(parts[3][1:])
            self.vregs[vd] = self.vregs[vs1] / self.vregs[vs2]

        elif op == 'VMAX':
            vd = int(parts[1][1:])
            vs1 = int(parts[2][1:])
            vs2 = int(parts[3][1:])
            self.vregs[vd] = np.maximum(self.vregs[vs1], self.vregs[vs2])

        elif op == 'VMAC':
            vd = int(parts[1][1:])
            vs1 = int(parts[2][1:])
            vs2 = int(parts[3][1:])
            self.vregs[vd] = self.vregs[vs1] * self.vregs[vs2]

        elif op == 'VSQRT':
            vd = int(parts[1][1:])
            vs = int(parts[2][1:])
            self.vregs[vd] = np.sqrt(self.vregs[vs]).astype(np.float32)

        elif op == 'VEXP':
            vd = int(parts[1][1:])
            vs = int(parts[2][1:])
            self.vregs[vd] = np.exp(self.vregs[vs]).astype(np.float32)

        elif op == 'VRECIP':
            vd = int(parts[1][1:])
            vs = int(parts[2][1:])
            self.vregs[vd] = (np.float32(1.0) / self.vregs[vs]).astype(np.float32)

        elif op == 'VNEG':
            vd = int(parts[1][1:])
            vs = int(parts[2][1:])
            self.vregs[vd] = -self.vregs[vs]

        elif op == 'VBCAST':
            vd = int(parts[1][1:])
            ss = int(parts[2][1:])
            self.vregs[vd][:] = self.sregs[ss]

        elif op == 'VREDSUM':
            sd = int(parts[1][1:])
            vs = int(parts[2][1:])
            val = float(np.sum(self.vregs[vs][:VLEN - 1]))
            if sd != 0:
                self.sregs[sd] = np.float32(val)

        elif op == 'VREDMAX':
            sd = int(parts[1][1:])
            vs = int(parts[2][1:])
            val = float(np.max(self.vregs[vs]))
            if sd != 0:
                self.sregs[sd] = np.float32(val)

        elif op == 'SMOV':
            sd = int(parts[1][1:])
            imm = float(parts[2].lstrip('#'))
            if sd != 0:
                self.sregs[sd] = np.float32(imm)

        elif op == 'SADD':
            sd = int(parts[1][1:])
            ss1 = int(parts[2][1:])
            ss2 = int(parts[3][1:])
            if sd != 0:
                self.sregs[sd] = np.float32(self.sregs[ss1] + self.sregs[ss2])

        elif op == 'SSUB':
            sd = int(parts[1][1:])
            ss1 = int(parts[2][1:])
            ss2 = int(parts[3][1:])
            if sd != 0:
                self.sregs[sd] = np.float32(self.sregs[ss1] - self.sregs[ss2])

        elif op == 'SMUL':
            sd = int(parts[1][1:])
            ss1 = int(parts[2][1:])
            ss2 = int(parts[3][1:])
            if sd != 0:
                self.sregs[sd] = np.float32(self.sregs[ss1] * self.sregs[ss2])

        elif op == 'SDIV':
            sd = int(parts[1][1:])
            ss1 = int(parts[2][1:])
            ss2 = int(parts[3][1:])
            if sd != 0:
                self.sregs[sd] = np.float32(self.sregs[ss1] / self.sregs[ss2])

        elif op == 'SSQRT':
            sd = int(parts[1][1:])
            ss = int(parts[2][1:])
            if sd != 0:
                self.sregs[sd] = np.float32(np.sqrt(self.sregs[ss]))

        elif op == 'SMAX':
            sd = int(parts[1][1:])
            ss1 = int(parts[2][1:])
            ss2 = int(parts[3][1:])
            if sd != 0:
                self.sregs[sd] = np.float32(max(self.sregs[ss1], self.sregs[ss2]))

        elif op == 'BNZ':
            ss = int(parts[1][1:])
            label = parts[2].lstrip('.')
            if self.sregs[ss] != 0.0:
                if label in self.labels:
                    self.pc = self.labels[label]
                    return
                else:
                    raise ValueError(f"Unknown label: {label}")

        elif op == 'DEC':
            sd = int(parts[1][1:])
            ss = int(parts[2][1:])
            if sd != 0:
                self.sregs[sd] = np.float32(self.sregs[ss] - 1.0)

        else:
            raise ValueError(f"Unknown instruction: {op} (line: {raw})")

        self.pc += 1


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python simulator.py <program.asm>")
        sys.exit(1)

    npu = MiniNPU()
    with open(sys.argv[1]) as f:
        npu.load_program(f.read())
    steps = npu.run()
    print(f"Execution completed in {steps} steps.")
