#!/usr/bin/env python3
"""LLVMlite to x86-64 compiler backend."""

import sys
import re
import argparse
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------

@dataclass
class Operand:
    kind: str   # 'reg', 'imm', 'global'
    value: str


@dataclass
class Instruction:
    opcode: str
    result: Optional[str]
    operands: List[Operand]
    extra: dict = field(default_factory=dict)


@dataclass
class BasicBlock:
    label: str
    instructions: List[Instruction]


@dataclass
class Function:
    name: str
    ret_type: str
    params: List[Tuple[str, str]]   # [(type, name), ...]
    blocks: List[BasicBlock]


@dataclass
class GlobalVar:
    name: str
    init_val: int


@dataclass
class ExternDecl:
    name: str
    ret_type: str
    param_types: List[str]


@dataclass
class Program:
    globals: List[GlobalVar]
    externs: List[ExternDecl]
    functions: List[Function]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class Parser:
    def __init__(self, source: str):
        self.lines: List[str] = []
        for raw in source.split('\n'):
            # Strip inline comments
            idx = raw.find(';')
            if idx != -1:
                raw = raw[:idx]
            self.lines.append(raw.strip())
        self.pos = 0

    # -- helpers --

    def _cur(self) -> str:
        return self.lines[self.pos] if self.pos < len(self.lines) else ''

    def _adv(self):
        self.pos += 1

    @staticmethod
    def _operand(s: str) -> Operand:
        s = s.strip()
        if s.startswith('%'):
            return Operand('reg', s[1:])
        if s.startswith('@'):
            return Operand('global', s[1:])
        return Operand('imm', s)

    # -- top-level --

    def parse(self) -> Program:
        globs: List[GlobalVar] = []
        externs: List[ExternDecl] = []
        funcs: List[Function] = []
        while self.pos < len(self.lines):
            line = self._cur()
            if not line:
                self._adv()
                continue
            if line.startswith('@') and '= global' in line:
                globs.append(self._global(line))
                self._adv()
            elif line.startswith('declare'):
                externs.append(self._extern(line))
                self._adv()
            elif line.startswith('define'):
                funcs.append(self._function())
            else:
                self._adv()
        return Program(globs, externs, funcs)

    def _global(self, line: str) -> GlobalVar:
        m = re.match(r'@(\w+)\s*=\s*global\s+\S+\s+(-?\d+)', line)
        assert m, f'Bad global: {line}'
        return GlobalVar(m.group(1), int(m.group(2)))

    def _extern(self, line: str) -> ExternDecl:
        m = re.match(r'declare\s+(\S+)\s+@(\w+)\s*\((.*?)\)', line)
        assert m, f'Bad extern: {line}'
        ps = m.group(3).strip()
        ptypes = [p.strip() for p in ps.split(',') if p.strip()] if ps else []
        return ExternDecl(m.group(2), m.group(1), ptypes)

    def _function(self) -> Function:
        line = self._cur()
        m = re.match(r'define\s+(\S+)\s+@(\w+)\s*\((.*?)\)\s*\{', line)
        assert m, f'Bad function def: {line}'
        ret_type, name = m.group(1), m.group(2)
        pstr = m.group(3).strip()
        params: List[Tuple[str, str]] = []
        if pstr:
            for p in pstr.split(','):
                parts = p.strip().split()
                params.append((parts[0], parts[1].lstrip('%')))
        self._adv()

        blocks: List[BasicBlock] = []
        cur_label: Optional[str] = None
        cur_ins: List[Instruction] = []

        while self.pos < len(self.lines):
            line = self._cur()
            if line == '}':
                if cur_ins or cur_label is not None:
                    blocks.append(BasicBlock(cur_label or 'entry', cur_ins))
                self._adv()
                break
            if not line:
                self._adv()
                continue
            lm = re.match(r'^(\w+)\s*:\s*$', line)
            if lm:
                if cur_ins:
                    blocks.append(BasicBlock(cur_label or 'entry', cur_ins))
                    cur_ins = []
                elif cur_label is not None:
                    blocks.append(BasicBlock(cur_label, []))
                cur_label = lm.group(1)
                self._adv()
                continue
            ins = self._instruction(line)
            if ins is not None:
                if cur_label is None:
                    cur_label = 'entry'
                cur_ins.append(ins)
            self._adv()

        return Function(name, ret_type, params, blocks)

    # -- instructions --

    def _instruction(self, line: str) -> Optional[Instruction]:
        result: Optional[str] = None
        if line.startswith('%'):
            m = re.match(r'%(\w+)\s*=\s*(.*)', line)
            if m:
                result = m.group(1)
                line = m.group(2).strip()
        if not line:
            return None
        opcode = line.split()[0]

        if opcode in ('add', 'sub', 'mul', 'and', 'or', 'xor',
                       'shl', 'lshr', 'ashr'):
            m = re.match(r'\w+\s+\S+\s+(.+?)\s*,\s*(.+)', line)
            assert m, f'Bad binop: {line}'
            return Instruction(opcode, result,
                               [self._operand(m.group(1)),
                                self._operand(m.group(2))])

        if opcode == 'icmp':
            m = re.match(r'icmp\s+(\w+)\s+\S+\s+(.+?)\s*,\s*(.+)', line)
            assert m, f'Bad icmp: {line}'
            return Instruction('icmp', result,
                               [self._operand(m.group(2)),
                                self._operand(m.group(3))],
                               {'cond': m.group(1)})

        if opcode == 'alloca':
            return Instruction('alloca', result, [])

        if opcode == 'load':
            m = re.match(r'load\s+\S+\s*,\s*\S+\s+(.+)', line)
            assert m, f'Bad load: {line}'
            return Instruction('load', result, [self._operand(m.group(1))])

        if opcode == 'store':
            m = re.match(r'store\s+\S+\s+(.+?)\s*,\s*\S+\s+(.+)', line)
            assert m, f'Bad store: {line}'
            return Instruction('store', None,
                               [self._operand(m.group(1)),
                                self._operand(m.group(2))])

        if opcode == 'call':
            m = re.match(r'call\s+(\S+)\s+@(\w+)\s*\((.*?)\)', line)
            assert m, f'Bad call: {line}'
            args: List[Operand] = []
            astr = m.group(3).strip()
            if astr:
                for a in astr.split(','):
                    tok = a.strip().split()
                    args.append(self._operand(tok[-1]))
            return Instruction('call', result, args,
                               {'func': m.group(2), 'ret_type': m.group(1)})

        if opcode == 'ret':
            if 'void' in line:
                return Instruction('ret', None, [])
            m = re.match(r'ret\s+\S+\s+(.+)', line)
            assert m, f'Bad ret: {line}'
            return Instruction('ret', None, [self._operand(m.group(1))])

        if opcode == 'br':
            cm = re.match(
                r'br\s+i1\s+(.+?)\s*,\s*label\s+%(\w+)\s*,\s*label\s+%(\w+)',
                line)
            if cm:
                return Instruction('br_cond', None,
                                   [self._operand(cm.group(1))],
                                   {'then': cm.group(2),
                                    'else': cm.group(3)})
            um = re.match(r'br\s+label\s+%(\w+)', line)
            assert um, f'Bad br: {line}'
            return Instruction('br', None, [],
                               {'target': um.group(1)})

        if opcode == 'getelementptr':
            m = re.match(
                r'getelementptr\s+(\S+)\s*,\s*\S+\s+(.+?)\s*,\s*\S+\s+(.+)',
                line)
            assert m, f'Bad gep: {line}'
            ety = m.group(1)
            esz = 8 if ety in ('i64', 'i64*') else (4 if ety == 'i32' else 1)
            return Instruction('gep', result,
                               [self._operand(m.group(2)),
                                self._operand(m.group(3))],
                               {'elem_size': esz})

        if opcode == 'zext':
            m = re.match(r'zext\s+\S+\s+(.+?)\s+to\s+\S+', line)
            assert m, f'Bad zext: {line}'
            return Instruction('zext', result, [self._operand(m.group(1))])

        if opcode == 'trunc':
            m = re.match(r'trunc\s+\S+\s+(.+?)\s+to\s+\S+', line)
            assert m, f'Bad trunc: {line}'
            return Instruction('trunc', result, [self._operand(m.group(1))])

        if opcode == 'bitcast':
            m = re.match(r'bitcast\s+\S+\s+(.+?)\s+to\s+\S+', line)
            assert m, f'Bad bitcast: {line}'
            return Instruction('bitcast', result, [self._operand(m.group(1))])

        return None


# ---------------------------------------------------------------------------
# x86-64 Code Generator
# ---------------------------------------------------------------------------

class CodeGen:
    ARG_REGS = ['%rdi', '%rsi', '%rdx', '%rcx', '%r8', '%r9']

    def __init__(self):
        self.out: List[str] = []

    def emit(self, s: str):
        self.out.append(s)

    # -- public --

    def generate(self, prog: Program) -> str:
        self.emit('.text')
        for func in prog.functions:
            self._function(func)
            self.emit('')
        if prog.globals:
            self.emit('.data')
            for g in prog.globals:
                self.emit(f'.globl {g.name}')
                self.emit(f'.align 8')
                self.emit(f'{g.name}:')
                self.emit(f'    .quad {g.init_val}')
            self.emit('')
        return '\n'.join(self.out) + '\n'

    # -- function --

    def _function(self, func: Function):
        # Assign stack slots
        slots: dict[str, int] = {}
        alloca_data: dict[str, int] = {}
        n = 0
        for _, pname in func.params:
            n += 1
            slots[pname] = -8 * n
        for blk in func.blocks:
            for ins in blk.instructions:
                if ins.result and ins.result not in slots:
                    n += 1
                    slots[ins.result] = -8 * n
                if ins.opcode == 'alloca' and ins.result:
                    n += 1
                    alloca_data[ins.result] = -8 * n

        frame = 8 * n
        if frame % 16 != 0:
            frame += 8

        # Prologue
        self.emit(f'.globl {func.name}')
        self.emit(f'{func.name}:')
        self.emit('    pushq %rbp')
        self.emit('    movq %rsp, %rbp')
        if frame:
            self.emit(f'    subq ${frame}, %rsp')

        # Store incoming args
        for i, (_, pname) in enumerate(func.params):
            off = slots[pname]
            if i < 6:
                self.emit(f'    movq {self.ARG_REGS[i]}, {off}(%rbp)')
            else:
                src = 16 + (i - 6) * 8
                self.emit(f'    movq {src}(%rbp), %rax')
                self.emit(f'    movq %rax, {off}(%rbp)')

        # Initialize alloca pointers
        for reg, doff in alloca_data.items():
            poff = slots[reg]
            self.emit(f'    leaq {doff}(%rbp), %rax')
            self.emit(f'    movq %rax, {poff}(%rbp)')

        # Blocks
        for blk in func.blocks:
            self.emit(f'.L{func.name}_{blk.label}:')
            for ins in blk.instructions:
                self._instr(ins, func, slots)

    # -- operand helpers --

    def _load_op(self, op: Operand, reg: str, slots: dict):
        """Load the runtime value of *op* into *reg*."""
        if op.kind == 'imm':
            self.emit(f'    movq ${op.value}, {reg}')
        elif op.kind == 'reg':
            self.emit(f'    movq {slots[op.value]}(%rbp), {reg}')
        elif op.kind == 'global':
            # Globals in LLVM are pointers; load the address.
            self.emit(f'    leaq {op.value}(%rip), {reg}')

    # -- instructions --

    def _instr(self, ins: Instruction, func: Function, slots: dict):
        op = ins.opcode

        # --- arithmetic / bitwise (non-shift) ---
        if op in ('add', 'sub', 'mul', 'and', 'or', 'xor'):
            asm = {'add': 'addq', 'sub': 'subq', 'mul': 'imulq',
                   'and': 'andq', 'or': 'orq', 'xor': 'xorq'}[op]
            self._load_op(ins.operands[0], '%rax', slots)
            self._load_op(ins.operands[1], '%rcx', slots)
            self.emit(f'    {asm} %rcx, %rax')
            self.emit(f'    movq %rax, {slots[ins.result]}(%rbp)')
            return

        # --- shifts ---
        if op in ('shl', 'lshr', 'ashr'):
            shift = {'shl': 'shlq', 'lshr': 'shrq', 'ashr': 'sarq'}[op]
            self._load_op(ins.operands[0], '%rax', slots)
            self._load_op(ins.operands[1], '%rcx', slots)
            self.emit(f'    {shift} %cl, %rax')
            self.emit(f'    movq %rax, {slots[ins.result]}(%rbp)')
            return

        # --- icmp ---
        if op == 'icmp':
            cc = ins.extra['cond']
            setcc = {'eq': 'sete', 'ne': 'setne', 'slt': 'setl',
                     'sgt': 'setg', 'sle': 'setle', 'sge': 'setge'}[cc]
            self._load_op(ins.operands[0], '%rax', slots)
            self._load_op(ins.operands[1], '%rcx', slots)
            self.emit('    cmpq %rcx, %rax')
            self.emit(f'    {setcc} %al')
            self.emit('    movzbq %al, %rax')
            self.emit(f'    movq %rax, {slots[ins.result]}(%rbp)')
            return

        # --- alloca (handled in prologue) ---
        if op == 'alloca':
            return

        # --- load ---
        if op == 'load':
            ptr = ins.operands[0]
            if ptr.kind == 'global':
                self.emit(f'    movq {ptr.value}(%rip), %rax')
            else:
                self._load_op(ptr, '%rax', slots)
                self.emit('    movq (%rax), %rax')
            self.emit(f'    movq %rax, {slots[ins.result]}(%rbp)')
            return

        # --- store ---
        if op == 'store':
            val, ptr = ins.operands[0], ins.operands[1]
            if ptr.kind == 'global':
                self._load_op(val, '%rax', slots)
                self.emit(f'    movq %rax, {ptr.value}(%rip)')
            else:
                self._load_op(val, '%rax', slots)
                self._load_op(ptr, '%rcx', slots)
                self.emit('    movq %rax, (%rcx)')
            return

        # --- call ---
        if op == 'call':
            fname = ins.extra['func']
            args = ins.operands
            n_stack = max(0, len(args) - 6)
            pad = 0
            if n_stack > 0 and n_stack % 2 != 0:
                pad = 8
                self.emit('    subq $8, %rsp')
            # Push stack args in reverse
            for i in range(len(args) - 1, 5, -1):
                self._load_op(args[i], '%rax', slots)
                self.emit('    pushq %rax')
            # Load register args
            for i in range(min(6, len(args))):
                self._load_op(args[i], self.ARG_REGS[i], slots)
            self.emit(f'    callq {fname}')
            cleanup = n_stack * 8 + pad
            if cleanup:
                self.emit(f'    addq ${cleanup}, %rsp')
            if ins.result:
                self.emit(f'    movq %rax, {slots[ins.result]}(%rbp)')
            return

        # --- ret ---
        if op == 'ret':
            if ins.operands:
                self._load_op(ins.operands[0], '%rax', slots)
            self.emit('    movq %rbp, %rsp')
            self.emit('    popq %rbp')
            self.emit('    retq')
            return

        # --- unconditional branch ---
        if op == 'br':
            self.emit(f'    jmp .L{func.name}_{ins.extra["target"]}')
            return

        # --- conditional branch ---
        if op == 'br_cond':
            self._load_op(ins.operands[0], '%rax', slots)
            self.emit('    testq %rax, %rax')
            self.emit(f'    jne .L{func.name}_{ins.extra["then"]}')
            self.emit(f'    jmp .L{func.name}_{ins.extra["else"]}')
            return

        # --- getelementptr ---
        if op == 'gep':
            esz = ins.extra['elem_size']
            self._load_op(ins.operands[0], '%rax', slots)
            self._load_op(ins.operands[1], '%rcx', slots)
            if esz > 1:
                self.emit(f'    imulq ${esz}, %rcx, %rcx')
            self.emit('    addq %rcx, %rax')
            self.emit(f'    movq %rax, {slots[ins.result]}(%rbp)')
            return

        # --- zext / bitcast (identity at 64-bit level) ---
        if op in ('zext', 'bitcast'):
            self._load_op(ins.operands[0], '%rax', slots)
            self.emit(f'    movq %rax, {slots[ins.result]}(%rbp)')
            return

        # --- trunc i64 -> i1 ---
        if op == 'trunc':
            self._load_op(ins.operands[0], '%rax', slots)
            self.emit('    andq $1, %rax')
            self.emit(f'    movq %rax, {slots[ins.result]}(%rbp)')
            return


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='LLVMlite to x86-64 compiler')
    ap.add_argument('input', help='Input .ll file')
    ap.add_argument('-o', '--output', required=True, help='Output .s file')
    args = ap.parse_args()

    with open(args.input) as f:
        source = f.read()

    prog = Parser(source).parse()
    asm = CodeGen().generate(prog)

    with open(args.output, 'w') as f:
        f.write(asm)


if __name__ == '__main__':
    main()
