
"""
Simplified x86-64 emulator for verifying register-allocated programs.

Handles the subset of x86 used by the register allocator task:
  movq, addq, subq, negq, xorq, cmpq,
  jmp, je, jne, jl, jle, jg, jge,
  sete, setne, setl, setle, setg, setge, movzbq,
  callq (print_int), pushq, popq

After callq, caller-saved registers are clobbered to detect
incorrect register allocation.
"""

CALLER_SAVED_REGS = ['rax', 'rcx', 'rdx', 'rsi', 'rdi', 'r8', 'r9', 'r10', 'r11']
CLOBBERED_VALUE = -7777777777


class EmulatorError(Exception):
    pass


class Emulator:
    def __init__(self):
        self.regs = {
            'rax': 0, 'rbx': 0, 'rcx': 0, 'rdx': 0,
            'rsi': 0, 'rdi': 0, 'rsp': 0x7FFF0000, 'rbp': 0x7FFF0000,
            'r8': 0, 'r9': 0, 'r10': 0, 'r11': 0,
            'r12': 0, 'r13': 0, 'r14': 0, 'r15': 0,
        }
        self.memory = {}
        self.flags = None  # 'e', 'l', or 'g'
        self.output = []

    def run(self, program):
        """Run program, return (rax_value, output_list)."""
        blocks = program['blocks']
        if 'start' in blocks:
            self._execute_block('start', blocks)
        else:
            first_label = next(iter(blocks))
            self._execute_block(first_label, blocks)
        return self.regs['rax'], self.output

    def _execute_block(self, label, blocks):
        if label == 'conclusion':
            return
        if label not in blocks:
            raise EmulatorError(f"Unknown block: {label}")
        instrs = blocks[label]
        for instr in instrs:
            jump_target = self._execute_instr(instr)
            if jump_target is not None:
                self._execute_block(jump_target, blocks)
                return

    def _read_arg(self, arg):
        kind = arg[0]
        if kind == 'imm':
            return arg[1]
        elif kind == 'reg':
            return self.regs[arg[1]]
        elif kind == 'deref':
            addr = self.regs[arg[1]] + arg[2]
            return self.memory.get(addr, 0)
        elif kind == 'var':
            raise EmulatorError(f"Unallocated variable: {arg[1]}")
        else:
            raise EmulatorError(f"Unknown arg type: {kind}")

    def _write_arg(self, arg, val):
        kind = arg[0]
        if kind == 'reg':
            self.regs[arg[1]] = val
        elif kind == 'deref':
            addr = self.regs[arg[1]] + arg[2]
            self.memory[addr] = val
        elif kind == 'var':
            raise EmulatorError(f"Unallocated variable: {arg[1]}")
        else:
            raise EmulatorError(f"Cannot write to arg type: {kind}")

    def _execute_instr(self, instr):
        op = instr[0]

        if op == 'movq':
            self._write_arg(instr[2], self._read_arg(instr[1]))

        elif op == 'addq':
            src = self._read_arg(instr[1])
            dst = self._read_arg(instr[2])
            self._write_arg(instr[2], dst + src)

        elif op == 'subq':
            src = self._read_arg(instr[1])
            dst = self._read_arg(instr[2])
            self._write_arg(instr[2], dst - src)

        elif op == 'negq':
            val = self._read_arg(instr[1])
            self._write_arg(instr[1], -val)

        elif op == 'xorq':
            src = self._read_arg(instr[1])
            dst = self._read_arg(instr[2])
            self._write_arg(instr[2], dst ^ src)

        elif op == 'cmpq':
            src = self._read_arg(instr[1])
            dst = self._read_arg(instr[2])
            diff = dst - src
            if diff == 0:
                self.flags = 'e'
            elif diff < 0:
                self.flags = 'l'
            else:
                self.flags = 'g'

        elif op == 'jmp':
            return instr[1]

        elif op in ('je', 'jne', 'jl', 'jle', 'jg', 'jge'):
            taken = False
            if op == 'je' and self.flags == 'e':
                taken = True
            elif op == 'jne' and self.flags != 'e':
                taken = True
            elif op == 'jl' and self.flags == 'l':
                taken = True
            elif op == 'jle' and self.flags in ('l', 'e'):
                taken = True
            elif op == 'jg' and self.flags == 'g':
                taken = True
            elif op == 'jge' and self.flags in ('g', 'e'):
                taken = True
            if taken:
                return instr[1]

        elif op == 'callq':
            func = instr[1]
            if func == 'print_int':
                self.output.append(self.regs['rdi'])
            # Clobber caller-saved registers to catch bad allocation
            for r in CALLER_SAVED_REGS:
                self.regs[r] = CLOBBERED_VALUE

        elif op in ('sete', 'setne', 'setl', 'setle', 'setg', 'setge'):
            cc = op[3:]
            val = 0
            if cc == 'e' and self.flags == 'e':
                val = 1
            elif cc == 'ne' and self.flags != 'e':
                val = 1
            elif cc == 'l' and self.flags == 'l':
                val = 1
            elif cc == 'le' and self.flags in ('l', 'e'):
                val = 1
            elif cc == 'g' and self.flags == 'g':
                val = 1
            elif cc == 'ge' and self.flags in ('g', 'e'):
                val = 1
            self._write_arg(instr[1], val)

        elif op == 'movzbq':
            self._write_arg(instr[2], self._read_arg(instr[1]))

        elif op == 'pushq':
            self.regs['rsp'] -= 8
            self.memory[self.regs['rsp']] = self._read_arg(instr[1])

        elif op == 'popq':
            self._write_arg(instr[1], self.memory.get(self.regs['rsp'], 0))
            self.regs['rsp'] += 8

        else:
            raise EmulatorError(f"Unknown instruction: {op}")

        return None
