
"""Simple x86 emulator for validating register-allocated programs.

Supports both pre-allocation (Var operands) and post-allocation (Reg/Deref operands).
After callq instructions, all caller-saved registers are clobbered with a sentinel
value to detect incorrect register assignments.
"""

from ir import Immediate, Reg, Var, Deref, Instr, Callq, Jump, JumpIf, CALLER_SAVED


CLOBBER_VALUE = 0xDEADDEADDEAD


class X86Emulator:
    def __init__(self):
        self.registers = {}
        self.variables = {}
        self.memory = {}
        self.flags = None
        self.registers['rbp'] = 100000
        self.registers['rsp'] = 100000

    def get_value(self, operand):
        if isinstance(operand, Immediate):
            return operand.value
        elif isinstance(operand, Reg):
            return self.registers.get(operand.name, 0)
        elif isinstance(operand, Var):
            return self.variables.get(operand.name, 0)
        elif isinstance(operand, Deref):
            addr = self.registers.get(operand.reg, 0) + operand.offset
            return self.memory.get(addr, 0)
        return 0

    def set_value(self, operand, value):
        if isinstance(operand, Reg):
            self.registers[operand.name] = value
        elif isinstance(operand, Var):
            self.variables[operand.name] = value
        elif isinstance(operand, Deref):
            addr = self.registers.get(operand.reg, 0) + operand.offset
            self.memory[addr] = value

    def check_cc(self, cc):
        if cc == 'e':
            return self.flags == 'e'
        elif cc == 'ne':
            return self.flags != 'e'
        elif cc == 'l':
            return self.flags == 'l'
        elif cc == 'le':
            return self.flags in ('l', 'e')
        elif cc == 'g':
            return self.flags == 'g'
        elif cc == 'ge':
            return self.flags in ('g', 'e')
        return False

    def execute(self, instr):
        """Execute one instruction. Returns a label string for jumps, None otherwise."""
        if isinstance(instr, Instr):
            name = instr.name
            if name == 'movq':
                self.set_value(instr.args[1], self.get_value(instr.args[0]))
            elif name == 'addq':
                v1 = self.get_value(instr.args[0])
                v2 = self.get_value(instr.args[1])
                self.set_value(instr.args[1], v1 + v2)
            elif name == 'subq':
                v1 = self.get_value(instr.args[0])
                v2 = self.get_value(instr.args[1])
                self.set_value(instr.args[1], v2 - v1)
            elif name == 'negq':
                v = self.get_value(instr.args[0])
                self.set_value(instr.args[0], -v)
            elif name == 'xorq':
                v1 = self.get_value(instr.args[0])
                v2 = self.get_value(instr.args[1])
                self.set_value(instr.args[1], v1 ^ v2)
            elif name == 'cmpq':
                v1 = self.get_value(instr.args[0])
                v2 = self.get_value(instr.args[1])
                if v2 == v1:
                    self.flags = 'e'
                elif v2 < v1:
                    self.flags = 'l'
                else:
                    self.flags = 'g'
            elif name == 'movzbq':
                v = self.get_value(instr.args[0])
                self.set_value(instr.args[1], v & 0xFF)
            elif name in ('sete', 'setne', 'setl', 'setle', 'setg', 'setge'):
                cc = name[3:]
                self.set_value(instr.args[0], 1 if self.check_cc(cc) else 0)
            return None

        elif isinstance(instr, Callq):
            # Clobber all caller-saved registers to detect misallocation
            for r in CALLER_SAVED:
                self.registers[r] = CLOBBER_VALUE
            return None

        elif isinstance(instr, Jump):
            return instr.label

        elif isinstance(instr, JumpIf):
            if self.check_cc(instr.cc):
                return instr.label
            return None

        return None

    def run(self, program):
        """Execute the program and return the value in %%rax at conclusion."""
        blocks = program.blocks
        current = 'start' if 'start' in blocks else 'main'
        max_steps = 100000

        for _ in range(max_steps):
            if current == 'conclusion':
                return self.registers.get('rax', 0)
            if current not in blocks:
                raise RuntimeError(f'Block {current!r} not found')

            instrs = blocks[current]
            jumped = False
            for instr in instrs:
                result = self.execute(instr)
                if result is not None:
                    current = result
                    jumped = True
                    break
            if not jumped:
                raise RuntimeError(f'Block {current!r} fell through without jump')

        raise RuntimeError('Exceeded maximum step count (possible infinite loop)')


def run_program(program):
    """Convenience function: run a program and return its result."""
    emu = X86Emulator()
    return emu.run(program)
