"""x86-64 emulator for verifying register allocation correctness.

Executes x86 programs represented as X86Program ASTs.
Supports both pre-allocation programs (with Variable nodes)
and post-allocation programs (with only Reg/Deref nodes).

Simulates the x86-64 calling convention by trashing caller-saved
registers after function calls.
"""

from collections import defaultdict
from x86_ast import (
    X86Program, Instr, Callq, Jump, JumpIf,
    Variable, Immediate, Reg, ByteReg, Deref,
)

# Sentinel value written to caller-saved registers after callq.
# Using a distinctive negative value that no correct program should produce.
TRASH_VALUE = -7777777


class X86Emulator:
    """Simple x86-64 emulator operating on X86Program AST nodes.

    Registers default to 0.  Variables (pre-allocation pseudo-registers)
    are stored in a separate namespace so they are unaffected by
    caller-saved register trashing.
    """

    def __init__(self):
        self.registers = defaultdict(lambda: 0)
        self.memory = defaultdict(lambda: 0)
        self.variables = defaultdict(lambda: 0)
        self.output = []
        # Initial stack pointer / base pointer
        self.registers['rbp'] = 1000
        self.registers['rsp'] = 1000

    # ------------------------------------------------------------------
    # Argument evaluation
    # ------------------------------------------------------------------

    def eval_arg(self, a):
        if isinstance(a, ByteReg):
            return self.registers[a.id]
        if isinstance(a, Reg):
            return self.registers[a.id]
        if isinstance(a, Variable):
            return self.variables[a.id]
        if isinstance(a, Immediate):
            return a.value
        if isinstance(a, Deref):
            addr = self.registers[a.reg] + a.offset
            return self.memory[addr]
        raise RuntimeError(f'eval_arg: unknown operand {a!r}')

    def store_arg(self, a, v):
        if isinstance(a, ByteReg):
            self.registers[a.id] = v
        elif isinstance(a, Reg):
            self.registers[a.id] = v
        elif isinstance(a, Variable):
            self.variables[a.id] = v
        elif isinstance(a, Deref):
            addr = self.registers[a.reg] + a.offset
            self.memory[addr] = v
        else:
            raise RuntimeError(f'store_arg: cannot store to {a!r}')

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, program: X86Program):
        """Execute *program* and return ``(rax_value, output_list)``."""
        self.output = []
        blocks = program.body

        if 'main' in blocks:
            self._eval_block(blocks, 'main')
        elif 'start' in blocks:
            self._eval_block(blocks, 'start')
        else:
            raise RuntimeError('No main or start block found')

        return self.registers['rax'], list(self.output)

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    def _eval_block(self, blocks, label):
        if label not in blocks:
            return
        for instr_node in blocks[label]:
            signal = self._eval_instr(instr_node, blocks)
            if signal == 'RETURN':
                return

    def _eval_instr(self, instr_node, blocks):  # noqa: C901 – complexity is inherent
        if isinstance(instr_node, Instr):
            return self._eval_plain_instr(instr_node, blocks)

        if isinstance(instr_node, Callq):
            return self._eval_callq(instr_node, blocks)

        if isinstance(instr_node, Jump):
            if instr_node.label in blocks:
                self._eval_block(blocks, instr_node.label)
            return 'RETURN'

        if isinstance(instr_node, JumpIf):
            return self._eval_jumpif(instr_node, blocks)

        raise RuntimeError(f'Unknown instruction type: {type(instr_node)}')

    def _eval_plain_instr(self, node, blocks):
        op = node.instr
        args = node.args

        if op == 'movq':
            self.store_arg(args[1], self.eval_arg(args[0]))
        elif op == 'movzbq':
            self.store_arg(args[1], self.eval_arg(args[0]))
        elif op == 'addq':
            self.store_arg(args[1],
                           self.eval_arg(args[0]) + self.eval_arg(args[1]))
        elif op == 'subq':
            self.store_arg(args[1],
                           self.eval_arg(args[1]) - self.eval_arg(args[0]))
        elif op == 'negq':
            self.store_arg(args[0], -self.eval_arg(args[0]))
        elif op == 'xorq':
            self.store_arg(args[1],
                           self.eval_arg(args[0]) ^ self.eval_arg(args[1]))
        elif op == 'cmpq':
            v1 = self.eval_arg(args[0])
            v2 = self.eval_arg(args[1])
            if v2 == v1:
                self.registers['EFLAGS'] = 'e'
            elif v2 < v1:
                self.registers['EFLAGS'] = 'l'
            else:
                self.registers['EFLAGS'] = 'g'
        elif op in ('sete', 'setne', 'setl', 'setle', 'setg', 'setge'):
            flag = self.registers['EFLAGS']
            result = 0
            if op == 'sete' and flag == 'e':
                result = 1
            elif op == 'setne' and flag != 'e':
                result = 1
            elif op == 'setl' and flag == 'l':
                result = 1
            elif op == 'setle' and flag in ('l', 'e'):
                result = 1
            elif op == 'setg' and flag == 'g':
                result = 1
            elif op == 'setge' and flag in ('g', 'e'):
                result = 1
            self.store_arg(args[0], result)
        elif op == 'pushq':
            self.registers['rsp'] -= 8
            self.memory[self.registers['rsp']] = self.eval_arg(args[0])
        elif op == 'popq':
            val = self.memory[self.registers['rsp']]
            self.registers['rsp'] += 8
            self.store_arg(args[0], val)
        elif op == 'retq':
            return 'RETURN'
        else:
            raise RuntimeError(f'Unknown instruction: {op}')
        return None

    def _eval_callq(self, node, blocks):
        if node.func == 'print_int':
            self.output.append(self.registers['rdi'])
        elif node.func == 'read_int':
            self.registers['rax'] = 0
        else:
            # User-defined function – execute its block
            self._eval_block(blocks, node.func)

        # Trash caller-saved registers (simulates calling convention)
        for reg in ('rax', 'rcx', 'rdx', 'rsi', 'rdi',
                    'r8', 'r9', 'r10', 'r11'):
            self.registers[reg] = TRASH_VALUE
        return None

    def _eval_jumpif(self, node, blocks):
        flag = self.registers['EFLAGS']
        jump = False
        cc = node.cc
        if cc == 'e' and flag == 'e':
            jump = True
        elif cc == 'ne' and flag != 'e':
            jump = True
        elif cc == 'l' and flag == 'l':
            jump = True
        elif cc == 'le' and flag in ('l', 'e'):
            jump = True
        elif cc == 'g' and flag == 'g':
            jump = True
        elif cc == 'ge' and flag in ('g', 'e'):
            jump = True

        if jump:
            if node.label in blocks:
                self._eval_block(blocks, node.label)
            return 'RETURN'
        return None
