"""VecTor-16 ISA Simulator.

A cycle-accurate simulator for the VecTor-16 custom vector processing unit.
"""

import math
import sys


class SimulatorError(Exception):
    """Base exception for simulator errors."""
    pass


class AlignmentError(SimulatorError):
    """Raised when a vector memory access is not aligned."""
    pass


class Simulator:
    """VecTor-16 ISA Simulator."""

    VLEN = 16
    NUM_VREG = 8
    NUM_SREG = 16
    NUM_AREG = 8

    CYCLES = {
        'VADD': 1, 'VSUB': 1, 'VMUL': 1, 'VMAX': 1, 'VMIN': 1,
        'VCOPY': 1, 'VFILL': 1, 'VNEG': 1, 'VABS': 1,
        'VADDS': 1, 'VSUBS': 1, 'VMULS': 1,
        'VDIV': 4, 'VDIVS': 4,
        'VEXP': 8, 'VSQRT': 8,
        'VREDSUM': 4, 'VREDMAX': 4, 'VREDMIN': 4,
        'VLOAD': 2, 'VSTORE': 2,
        'SLOAD': 1, 'SSTORE': 1,
        'SADD': 1, 'SSUB': 1, 'SMUL': 1, 'SMAX': 1, 'SMIN': 1,
        'SDIV': 2, 'SEXP': 4, 'SSQRT': 4,
        'SSET': 1, 'SCOPY': 1,
        'ASET': 1, 'AADD': 1, 'ACOPY': 1,
        'NOP': 1, 'HALT': 0,
        'JMP': 1, 'JLT': 1, 'JLE': 1, 'JGT': 1, 'JGE': 1, 'JEQ': 1, 'JNE': 1,
        'LABEL': 0,
    }

    def __init__(self, memory_size=65536):
        self.memory = [0.0] * memory_size
        self.memory_size = memory_size
        self.vreg = [[0.0] * self.VLEN for _ in range(self.NUM_VREG)]
        self.sreg = [0.0] * self.NUM_SREG
        self.areg = [0] * self.NUM_AREG
        self.cycles = 0
        self.pc = 0
        self.instructions = []
        self.labels = {}
        self.halted = False

    def load_memory(self, addr, data):
        """Load a list of float values into memory starting at addr."""
        for i, val in enumerate(data):
            if addr + i >= self.memory_size:
                raise SimulatorError(f"Memory write out of bounds: address {addr + i}")
            self.memory[addr + i] = float(val)

    def read_memory(self, addr, count):
        """Read count float values from memory starting at addr."""
        if addr + count > self.memory_size:
            raise SimulatorError(f"Memory read out of bounds: address {addr + count - 1}")
        return self.memory[addr:addr + count]

    def parse_program(self, source):
        """Parse assembly source code into an instruction list."""
        self.instructions = []
        self.labels = {}

        lines = source.strip().split('\n')
        for line in lines:
            line = line.strip()
            if '#' in line:
                line = line[:line.index('#')].strip()
            if not line:
                continue

            parts = line.replace(',', ' ').split()
            if not parts:
                continue

            opcode = parts[0].upper()
            operands = [p.strip() for p in parts[1:] if p.strip()]

            if opcode == 'LABEL':
                if not operands:
                    raise SimulatorError("LABEL requires a name")
                label_name = operands[0]
                if label_name in self.labels:
                    raise SimulatorError(f"Duplicate label: {label_name}")
                self.labels[label_name] = len(self.instructions)
                self.instructions.append(('LABEL', [label_name]))
            else:
                self.instructions.append((opcode, operands))

    def _parse_vreg(self, s):
        s = s.lower()
        if not s.startswith('v'):
            raise SimulatorError(f"Expected vector register, got '{s}'")
        try:
            idx = int(s[1:])
        except ValueError:
            raise SimulatorError(f"Invalid vector register: '{s}'")
        if idx < 0 or idx >= self.NUM_VREG:
            raise SimulatorError(f"Vector register out of range: {s} (valid: v0-v{self.NUM_VREG - 1})")
        return idx

    def _parse_sreg(self, s):
        s = s.lower()
        if not s.startswith('s'):
            raise SimulatorError(f"Expected scalar register, got '{s}'")
        try:
            idx = int(s[1:])
        except ValueError:
            raise SimulatorError(f"Invalid scalar register: '{s}'")
        if idx < 0 or idx >= self.NUM_SREG:
            raise SimulatorError(f"Scalar register out of range: {s} (valid: s0-s{self.NUM_SREG - 1})")
        return idx

    def _parse_areg(self, s):
        s = s.lower()
        if not s.startswith('a'):
            raise SimulatorError(f"Expected address register, got '{s}'")
        try:
            idx = int(s[1:])
        except ValueError:
            raise SimulatorError(f"Invalid address register: '{s}'")
        if idx < 0 or idx >= self.NUM_AREG:
            raise SimulatorError(f"Address register out of range: {s} (valid: a0-a{self.NUM_AREG - 1})")
        return idx

    def _parse_float(self, s):
        try:
            return float(s)
        except ValueError:
            raise SimulatorError(f"Invalid float literal: '{s}'")

    def _parse_int(self, s):
        try:
            return int(s)
        except ValueError:
            raise SimulatorError(f"Invalid integer literal: '{s}'")

    def execute(self, max_cycles=1000000):
        """Execute the loaded program. Returns (cycles, instruction_count)."""
        self.pc = 0
        self.cycles = 0
        self.halted = False
        instruction_count = 0

        while not self.halted and self.pc < len(self.instructions):
            if self.cycles >= max_cycles:
                raise SimulatorError(f"Exceeded maximum cycle count ({max_cycles})")

            opcode, operands = self.instructions[self.pc]
            self.pc += 1
            instruction_count += 1

            self.cycles += self.CYCLES.get(opcode, 1)
            self._execute_instruction(opcode, operands)

        return self.cycles, instruction_count

    def _safe_exp(self, x):
        if x > 88.0:
            return float('inf')
        elif x < -88.0:
            return 0.0
        return math.exp(x)

    def _execute_instruction(self, opcode, operands):
        # ---- Vector Arithmetic ----
        if opcode == 'VADD':
            d, s1, s2 = self._parse_vreg(operands[0]), self._parse_vreg(operands[1]), self._parse_vreg(operands[2])
            self.vreg[d] = [self.vreg[s1][i] + self.vreg[s2][i] for i in range(self.VLEN)]

        elif opcode == 'VSUB':
            d, s1, s2 = self._parse_vreg(operands[0]), self._parse_vreg(operands[1]), self._parse_vreg(operands[2])
            self.vreg[d] = [self.vreg[s1][i] - self.vreg[s2][i] for i in range(self.VLEN)]

        elif opcode == 'VMUL':
            d, s1, s2 = self._parse_vreg(operands[0]), self._parse_vreg(operands[1]), self._parse_vreg(operands[2])
            self.vreg[d] = [self.vreg[s1][i] * self.vreg[s2][i] for i in range(self.VLEN)]

        elif opcode == 'VDIV':
            d, s1, s2 = self._parse_vreg(operands[0]), self._parse_vreg(operands[1]), self._parse_vreg(operands[2])
            result = []
            for i in range(self.VLEN):
                if self.vreg[s2][i] == 0.0:
                    result.append(float('inf') if self.vreg[s1][i] >= 0 else float('-inf'))
                else:
                    result.append(self.vreg[s1][i] / self.vreg[s2][i])
            self.vreg[d] = result

        elif opcode == 'VEXP':
            d, s1 = self._parse_vreg(operands[0]), self._parse_vreg(operands[1])
            self.vreg[d] = [self._safe_exp(self.vreg[s1][i]) for i in range(self.VLEN)]

        elif opcode == 'VSQRT':
            d, s1 = self._parse_vreg(operands[0]), self._parse_vreg(operands[1])
            self.vreg[d] = [math.sqrt(max(0.0, self.vreg[s1][i])) for i in range(self.VLEN)]

        elif opcode == 'VABS':
            d, s1 = self._parse_vreg(operands[0]), self._parse_vreg(operands[1])
            self.vreg[d] = [abs(self.vreg[s1][i]) for i in range(self.VLEN)]

        elif opcode == 'VNEG':
            d, s1 = self._parse_vreg(operands[0]), self._parse_vreg(operands[1])
            self.vreg[d] = [-self.vreg[s1][i] for i in range(self.VLEN)]

        elif opcode == 'VMAX':
            d, s1, s2 = self._parse_vreg(operands[0]), self._parse_vreg(operands[1]), self._parse_vreg(operands[2])
            self.vreg[d] = [max(self.vreg[s1][i], self.vreg[s2][i]) for i in range(self.VLEN)]

        elif opcode == 'VMIN':
            d, s1, s2 = self._parse_vreg(operands[0]), self._parse_vreg(operands[1]), self._parse_vreg(operands[2])
            self.vreg[d] = [min(self.vreg[s1][i], self.vreg[s2][i]) for i in range(self.VLEN)]

        # ---- Vector-Scalar ----
        elif opcode == 'VADDS':
            d, vs, ss = self._parse_vreg(operands[0]), self._parse_vreg(operands[1]), self._parse_sreg(operands[2])
            self.vreg[d] = [self.vreg[vs][i] + self.sreg[ss] for i in range(self.VLEN)]

        elif opcode == 'VSUBS':
            d, vs, ss = self._parse_vreg(operands[0]), self._parse_vreg(operands[1]), self._parse_sreg(operands[2])
            self.vreg[d] = [self.vreg[vs][i] - self.sreg[ss] for i in range(self.VLEN)]

        elif opcode == 'VMULS':
            d, vs, ss = self._parse_vreg(operands[0]), self._parse_vreg(operands[1]), self._parse_sreg(operands[2])
            self.vreg[d] = [self.vreg[vs][i] * self.sreg[ss] for i in range(self.VLEN)]

        elif opcode == 'VDIVS':
            d, vs, ss = self._parse_vreg(operands[0]), self._parse_vreg(operands[1]), self._parse_sreg(operands[2])
            val = self.sreg[ss]
            if val == 0.0:
                self.vreg[d] = [float('inf') if self.vreg[vs][i] >= 0 else float('-inf') for i in range(self.VLEN)]
            else:
                self.vreg[d] = [self.vreg[vs][i] / val for i in range(self.VLEN)]

        # ---- Reductions ----
        elif opcode == 'VREDSUM':
            sd, vs = self._parse_sreg(operands[0]), self._parse_vreg(operands[1])
            self.sreg[sd] = sum(self.vreg[vs])

        elif opcode == 'VREDMAX':
            sd, vs = self._parse_sreg(operands[0]), self._parse_vreg(operands[1])
            self.sreg[sd] = max(self.vreg[vs])

        elif opcode == 'VREDMIN':
            sd, vs = self._parse_sreg(operands[0]), self._parse_vreg(operands[1])
            self.sreg[sd] = min(self.vreg[vs])

        # ---- Vector Memory ----
        elif opcode == 'VLOAD':
            vd = self._parse_vreg(operands[0])
            ab = self._parse_areg(operands[1])
            offset = self._parse_int(operands[2])
            addr = self.areg[ab] + offset
            if addr % self.VLEN != 0:
                raise AlignmentError(
                    f"VLOAD: effective address {addr} is not aligned to {self.VLEN}-element boundary "
                    f"(abase={self.areg[ab]}, offset={offset})"
                )
            if addr < 0 or addr + self.VLEN > self.memory_size:
                raise SimulatorError(f"VLOAD: address {addr} out of bounds")
            self.vreg[vd] = list(self.memory[addr:addr + self.VLEN])

        elif opcode == 'VSTORE':
            vs = self._parse_vreg(operands[0])
            ab = self._parse_areg(operands[1])
            offset = self._parse_int(operands[2])
            addr = self.areg[ab] + offset
            if addr % self.VLEN != 0:
                raise AlignmentError(
                    f"VSTORE: effective address {addr} is not aligned to {self.VLEN}-element boundary "
                    f"(abase={self.areg[ab]}, offset={offset})"
                )
            if addr < 0 or addr + self.VLEN > self.memory_size:
                raise SimulatorError(f"VSTORE: address {addr} out of bounds")
            for i in range(self.VLEN):
                self.memory[addr + i] = self.vreg[vs][i]

        # ---- Scalar Memory ----
        elif opcode == 'SLOAD':
            sd = self._parse_sreg(operands[0])
            ab = self._parse_areg(operands[1])
            offset = self._parse_int(operands[2])
            addr = self.areg[ab] + offset
            if addr < 0 or addr >= self.memory_size:
                raise SimulatorError(f"SLOAD: address {addr} out of bounds")
            self.sreg[sd] = self.memory[addr]

        elif opcode == 'SSTORE':
            ss = self._parse_sreg(operands[0])
            ab = self._parse_areg(operands[1])
            offset = self._parse_int(operands[2])
            addr = self.areg[ab] + offset
            if addr < 0 or addr >= self.memory_size:
                raise SimulatorError(f"SSTORE: address {addr} out of bounds")
            self.memory[addr] = self.sreg[ss]

        # ---- Scalar Arithmetic ----
        elif opcode == 'SADD':
            d, s1, s2 = self._parse_sreg(operands[0]), self._parse_sreg(operands[1]), self._parse_sreg(operands[2])
            self.sreg[d] = self.sreg[s1] + self.sreg[s2]

        elif opcode == 'SSUB':
            d, s1, s2 = self._parse_sreg(operands[0]), self._parse_sreg(operands[1]), self._parse_sreg(operands[2])
            self.sreg[d] = self.sreg[s1] - self.sreg[s2]

        elif opcode == 'SMUL':
            d, s1, s2 = self._parse_sreg(operands[0]), self._parse_sreg(operands[1]), self._parse_sreg(operands[2])
            self.sreg[d] = self.sreg[s1] * self.sreg[s2]

        elif opcode == 'SDIV':
            d, s1, s2 = self._parse_sreg(operands[0]), self._parse_sreg(operands[1]), self._parse_sreg(operands[2])
            if self.sreg[s2] == 0.0:
                self.sreg[d] = float('inf') if self.sreg[s1] >= 0 else float('-inf')
            else:
                self.sreg[d] = self.sreg[s1] / self.sreg[s2]

        elif opcode == 'SEXP':
            d, s1 = self._parse_sreg(operands[0]), self._parse_sreg(operands[1])
            self.sreg[d] = self._safe_exp(self.sreg[s1])

        elif opcode == 'SSQRT':
            d, s1 = self._parse_sreg(operands[0]), self._parse_sreg(operands[1])
            self.sreg[d] = math.sqrt(max(0.0, self.sreg[s1]))

        elif opcode == 'SMAX':
            d, s1, s2 = self._parse_sreg(operands[0]), self._parse_sreg(operands[1]), self._parse_sreg(operands[2])
            self.sreg[d] = max(self.sreg[s1], self.sreg[s2])

        elif opcode == 'SMIN':
            d, s1, s2 = self._parse_sreg(operands[0]), self._parse_sreg(operands[1]), self._parse_sreg(operands[2])
            self.sreg[d] = min(self.sreg[s1], self.sreg[s2])

        elif opcode == 'SSET':
            d = self._parse_sreg(operands[0])
            self.sreg[d] = self._parse_float(operands[1])

        elif opcode == 'SCOPY':
            d, s = self._parse_sreg(operands[0]), self._parse_sreg(operands[1])
            self.sreg[d] = self.sreg[s]

        # ---- Address ----
        elif opcode == 'ASET':
            d = self._parse_areg(operands[0])
            self.areg[d] = self._parse_int(operands[1])

        elif opcode == 'AADD':
            d, s, imm = self._parse_areg(operands[0]), self._parse_areg(operands[1]), self._parse_int(operands[2])
            self.areg[d] = self.areg[s] + imm

        elif opcode == 'ACOPY':
            d, s = self._parse_areg(operands[0]), self._parse_areg(operands[1])
            self.areg[d] = self.areg[s]

        # ---- Vector Utility ----
        elif opcode == 'VCOPY':
            d, s = self._parse_vreg(operands[0]), self._parse_vreg(operands[1])
            self.vreg[d] = list(self.vreg[s])

        elif opcode == 'VFILL':
            d, ss = self._parse_vreg(operands[0]), self._parse_sreg(operands[1])
            self.vreg[d] = [self.sreg[ss]] * self.VLEN

        # ---- Control Flow ----
        elif opcode == 'LABEL':
            pass

        elif opcode == 'JMP':
            target = operands[0]
            if target not in self.labels:
                raise SimulatorError(f"Unknown label: '{target}'")
            self.pc = self.labels[target]

        elif opcode == 'JLT':
            s1, s2 = self._parse_sreg(operands[0]), self._parse_sreg(operands[1])
            target = operands[2]
            if target not in self.labels:
                raise SimulatorError(f"Unknown label: '{target}'")
            if self.sreg[s1] < self.sreg[s2]:
                self.pc = self.labels[target]

        elif opcode == 'JLE':
            s1, s2 = self._parse_sreg(operands[0]), self._parse_sreg(operands[1])
            target = operands[2]
            if target not in self.labels:
                raise SimulatorError(f"Unknown label: '{target}'")
            if self.sreg[s1] <= self.sreg[s2]:
                self.pc = self.labels[target]

        elif opcode == 'JGT':
            s1, s2 = self._parse_sreg(operands[0]), self._parse_sreg(operands[1])
            target = operands[2]
            if target not in self.labels:
                raise SimulatorError(f"Unknown label: '{target}'")
            if self.sreg[s1] > self.sreg[s2]:
                self.pc = self.labels[target]

        elif opcode == 'JGE':
            s1, s2 = self._parse_sreg(operands[0]), self._parse_sreg(operands[1])
            target = operands[2]
            if target not in self.labels:
                raise SimulatorError(f"Unknown label: '{target}'")
            if self.sreg[s1] >= self.sreg[s2]:
                self.pc = self.labels[target]

        elif opcode == 'JEQ':
            s1, s2 = self._parse_sreg(operands[0]), self._parse_sreg(operands[1])
            target = operands[2]
            if target not in self.labels:
                raise SimulatorError(f"Unknown label: '{target}'")
            if abs(self.sreg[s1] - self.sreg[s2]) < 1e-10:
                self.pc = self.labels[target]

        elif opcode == 'JNE':
            s1, s2 = self._parse_sreg(operands[0]), self._parse_sreg(operands[1])
            target = operands[2]
            if target not in self.labels:
                raise SimulatorError(f"Unknown label: '{target}'")
            if abs(self.sreg[s1] - self.sreg[s2]) >= 1e-10:
                self.pc = self.labels[target]

        elif opcode == 'NOP':
            pass

        elif opcode == 'HALT':
            self.halted = True

        else:
            raise SimulatorError(f"Unknown opcode: '{opcode}' at instruction {self.pc - 1}")


def main():
    """CLI entry point: run an assembly file on the simulator."""
    if len(sys.argv) < 2:
        print(f"Usage: python3 {sys.argv[0]} <program.asm> [--trace]")
        sys.exit(1)

    asm_path = sys.argv[1]
    trace = '--trace' in sys.argv

    with open(asm_path, 'r') as f:
        source = f.read()

    sim = Simulator(memory_size=65536)
    sim.parse_program(source)

    print(f"Loaded {len(sim.instructions)} instructions, {len(sim.labels)} labels")

    try:
        cycles, instr_count = sim.execute(max_cycles=500000)
        print(f"Execution complete: {cycles} cycles, {instr_count} instructions executed")
        if sim.halted:
            print("Program terminated via HALT")
        else:
            print("Program fell off end of instruction list")
    except SimulatorError as e:
        print(f"Simulator error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
