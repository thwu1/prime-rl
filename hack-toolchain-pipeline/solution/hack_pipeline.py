#!/usr/bin/env python3
"""
Hack VM-to-Execution Pipeline.
Implements VM Translator, Assembler, and CPU Emulator for the Hack platform.
"""

import os
import sys
import glob
import tempfile

# ===========================================================================
# VM TRANSLATOR
# ===========================================================================

class VMParser:
    ARITHMETIC = {'add', 'sub', 'neg', 'eq', 'gt', 'lt', 'and', 'or', 'not'}

    def __init__(self, filename):
        with open(filename) as f:
            self.lines = []
            for line in f:
                line = line.split('//')[0].strip()
                if line:
                    self.lines.append(line)
        self.pos = -1
        self._parts = []

    def has_more(self):
        return self.pos < len(self.lines) - 1

    def advance(self):
        self.pos += 1
        self._parts = self.lines[self.pos].split()

    def cmd_type(self):
        c = self._parts[0]
        if c in self.ARITHMETIC:
            return 'C_ARITHMETIC'
        return {'push': 'C_PUSH', 'pop': 'C_POP', 'label': 'C_LABEL',
                'goto': 'C_GOTO', 'if-goto': 'C_IF', 'function': 'C_FUNCTION',
                'call': 'C_CALL', 'return': 'C_RETURN'}.get(c)

    def arg1(self):
        if self.cmd_type() == 'C_ARITHMETIC':
            return self._parts[0]
        return self._parts[1]

    def arg2(self):
        return int(self._parts[2])


class VMCodeWriter:
    SEG_BASE = {'local': 'LCL', 'argument': 'ARG', 'this': 'THIS', 'that': 'THAT'}

    def __init__(self):
        self.out = []
        self._lc = 0
        self.current_file = ''
        self.current_func = ''

    def set_filename(self, path):
        self.current_file = os.path.splitext(os.path.basename(path))[0]

    def _emit(self, s):
        self.out.append(s)

    def _label(self, prefix):
        self._lc += 1
        return f'$__{prefix}.{self._lc}'

    # --- Bootstrap ---
    def write_init(self):
        self._emit('@256')
        self._emit('D=A')
        self._emit('@SP')
        self._emit('M=D')
        self.write_call('Sys.init', 0)

    # --- Arithmetic ---
    def write_arithmetic(self, cmd):
        if cmd in ('add', 'sub', 'and', 'or'):
            op = {'add': 'D+M', 'sub': 'M-D', 'and': 'D&M', 'or': 'D|M'}[cmd]
            self._emit('@SP')
            self._emit('AM=M-1')
            self._emit('D=M')
            self._emit('@SP')
            self._emit('A=M-1')
            self._emit(f'M={op}')
        elif cmd in ('neg', 'not'):
            op = '-M' if cmd == 'neg' else '!M'
            self._emit('@SP')
            self._emit('A=M-1')
            self._emit(f'M={op}')
        elif cmd in ('eq', 'gt', 'lt'):
            jmp = {'eq': 'JEQ', 'gt': 'JGT', 'lt': 'JLT'}[cmd]
            lbl_t = self._label('TRUE')
            lbl_e = self._label('END')
            self._emit('@SP')
            self._emit('AM=M-1')
            self._emit('D=M')
            self._emit('@SP')
            self._emit('A=M-1')
            self._emit('D=M-D')
            self._emit(f'@{lbl_t}')
            self._emit(f'D;{jmp}')
            self._emit('@SP')
            self._emit('A=M-1')
            self._emit('M=0')
            self._emit(f'@{lbl_e}')
            self._emit('0;JMP')
            self._emit(f'({lbl_t})')
            self._emit('@SP')
            self._emit('A=M-1')
            self._emit('M=-1')
            self._emit(f'({lbl_e})')

    # --- Push / Pop ---
    def write_push(self, segment, index):
        if segment == 'constant':
            self._emit(f'@{index}')
            self._emit('D=A')
        elif segment in self.SEG_BASE:
            self._emit(f'@{self.SEG_BASE[segment]}')
            self._emit('D=M')
            self._emit(f'@{index}')
            self._emit('A=D+A')
            self._emit('D=M')
        elif segment == 'temp':
            self._emit(f'@{5 + index}')
            self._emit('D=M')
        elif segment == 'pointer':
            self._emit(f'@{"THIS" if index == 0 else "THAT"}')
            self._emit('D=M')
        elif segment == 'static':
            self._emit(f'@{self.current_file}.{index}')
            self._emit('D=M')
        self._push_d()

    def write_pop(self, segment, index):
        if segment in self.SEG_BASE:
            self._emit(f'@{self.SEG_BASE[segment]}')
            self._emit('D=M')
            self._emit(f'@{index}')
            self._emit('D=D+A')
            self._emit('@R13')
            self._emit('M=D')
            self._pop_to_d()
            self._emit('@R13')
            self._emit('A=M')
            self._emit('M=D')
        elif segment == 'temp':
            self._pop_to_d()
            self._emit(f'@{5 + index}')
            self._emit('M=D')
        elif segment == 'pointer':
            self._pop_to_d()
            self._emit(f'@{"THIS" if index == 0 else "THAT"}')
            self._emit('M=D')
        elif segment == 'static':
            self._pop_to_d()
            self._emit(f'@{self.current_file}.{index}')
            self._emit('M=D')

    # --- Program Flow ---
    def write_label(self, label):
        self._emit(f'({self.current_func}${label})')

    def write_goto(self, label):
        self._emit(f'@{self.current_func}${label}')
        self._emit('0;JMP')

    def write_if_goto(self, label):
        self._pop_to_d()
        self._emit(f'@{self.current_func}${label}')
        self._emit('D;JNE')

    # --- Functions ---
    def write_function(self, name, n_locals):
        self.current_func = name
        self._emit(f'({name})')
        for _ in range(n_locals):
            self._emit('@SP')
            self._emit('A=M')
            self._emit('M=0')
            self._emit('@SP')
            self._emit('M=M+1')

    def write_call(self, name, n_args):
        ret = self._label('RET')
        # push return address
        self._emit(f'@{ret}')
        self._emit('D=A')
        self._push_d()
        # push LCL, ARG, THIS, THAT
        for seg in ('LCL', 'ARG', 'THIS', 'THAT'):
            self._emit(f'@{seg}')
            self._emit('D=M')
            self._push_d()
        # ARG = SP - n_args - 5
        self._emit('@SP')
        self._emit('D=M')
        self._emit(f'@{n_args + 5}')
        self._emit('D=D-A')
        self._emit('@ARG')
        self._emit('M=D')
        # LCL = SP
        self._emit('@SP')
        self._emit('D=M')
        self._emit('@LCL')
        self._emit('M=D')
        # goto function
        self._emit(f'@{name}')
        self._emit('0;JMP')
        # return label
        self._emit(f'({ret})')

    def write_return(self):
        # FRAME (R14) = LCL
        self._emit('@LCL')
        self._emit('D=M')
        self._emit('@R14')
        self._emit('M=D')
        # RET (R15) = *(FRAME-5)
        self._emit('@5')
        self._emit('A=D-A')
        self._emit('D=M')
        self._emit('@R15')
        self._emit('M=D')
        # *ARG = pop()
        self._pop_to_d()
        self._emit('@ARG')
        self._emit('A=M')
        self._emit('M=D')
        # SP = ARG+1
        self._emit('@ARG')
        self._emit('D=M+1')
        self._emit('@SP')
        self._emit('M=D')
        # Restore THAT, THIS, ARG, LCL
        for seg, off in (('THAT', 1), ('THIS', 2), ('ARG', 3), ('LCL', 4)):
            self._emit('@R14')
            self._emit('D=M')
            self._emit(f'@{off}')
            self._emit('A=D-A')
            self._emit('D=M')
            self._emit(f'@{seg}')
            self._emit('M=D')
        # goto RET
        self._emit('@R15')
        self._emit('A=M')
        self._emit('0;JMP')

    # --- Helpers ---
    def _push_d(self):
        self._emit('@SP')
        self._emit('A=M')
        self._emit('M=D')
        self._emit('@SP')
        self._emit('M=M+1')

    def _pop_to_d(self):
        self._emit('@SP')
        self._emit('AM=M-1')
        self._emit('D=M')

    def get_asm(self):
        return '\n'.join(self.out) + '\n'


def translate_vm(vm_files, output_asm, bootstrap=False):
    """Translate VM file(s) to Hack assembly."""
    if isinstance(vm_files, str):
        vm_files = [vm_files]
    writer = VMCodeWriter()
    if bootstrap:
        writer.write_init()
    for vf in vm_files:
        writer.set_filename(vf)
        p = VMParser(vf)
        while p.has_more():
            p.advance()
            ct = p.cmd_type()
            if ct == 'C_ARITHMETIC':
                writer.write_arithmetic(p.arg1())
            elif ct == 'C_PUSH':
                writer.write_push(p.arg1(), p.arg2())
            elif ct == 'C_POP':
                writer.write_pop(p.arg1(), p.arg2())
            elif ct == 'C_LABEL':
                writer.write_label(p.arg1())
            elif ct == 'C_GOTO':
                writer.write_goto(p.arg1())
            elif ct == 'C_IF':
                writer.write_if_goto(p.arg1())
            elif ct == 'C_FUNCTION':
                writer.write_function(p.arg1(), p.arg2())
            elif ct == 'C_CALL':
                writer.write_call(p.arg1(), p.arg2())
            elif ct == 'C_RETURN':
                writer.write_return()
    with open(output_asm, 'w') as f:
        f.write(writer.get_asm())


# ===========================================================================
# ASSEMBLER
# ===========================================================================

_PREDEF = {
    'SP': 0, 'LCL': 1, 'ARG': 2, 'THIS': 3, 'THAT': 4,
    'R0': 0, 'R1': 1, 'R2': 2, 'R3': 3, 'R4': 4, 'R5': 5,
    'R6': 6, 'R7': 7, 'R8': 8, 'R9': 9, 'R10': 10, 'R11': 11,
    'R12': 12, 'R13': 13, 'R14': 14, 'R15': 15,
    'SCREEN': 16384, 'KBD': 24576,
}

_COMP = {
    '0':   '0101010', '1':   '0111111', '-1':  '0111010',
    'D':   '0001100', 'A':   '0110000', '!D':  '0001101',
    '!A':  '0110001', '-D':  '0001111', '-A':  '0110011',
    'D+1': '0011111', 'A+1': '0110111', 'D-1': '0001110',
    'A-1': '0110010', 'D+A': '0000010', 'D-A': '0010011',
    'A-D': '0000111', 'D&A': '0000000', 'D|A': '0010101',
    'M':   '1110000', '!M':  '1110001', '-M':  '1110011',
    'M+1': '1110111', 'M-1': '1110010', 'D+M': '1000010',
    'D-M': '1010011', 'M-D': '1000111', 'D&M': '1000000',
    'D|M': '1010101',
}

_DEST = {
    '': '000', 'M': '001', 'D': '010', 'MD': '011', 'DM': '011',
    'A': '100', 'AM': '101', 'MA': '101', 'AD': '110', 'DA': '110',
    'AMD': '111', 'ADM': '111', 'DAM': '111', 'DMA': '111',
    'MAD': '111', 'MDA': '111',
}

_JUMP = {
    '': '000', 'JGT': '001', 'JEQ': '010', 'JGE': '011',
    'JLT': '100', 'JNE': '101', 'JLE': '110', 'JMP': '111',
}


def assemble(asm_file, output_hack):
    """Assemble Hack assembly to binary."""
    with open(asm_file) as f:
        raw = f.readlines()

    # Strip comments and blanks
    cleaned = []
    for line in raw:
        line = line.split('//')[0].strip()
        if line:
            cleaned.append(line)

    # Pass 1: collect labels
    symbols = dict(_PREDEF)
    rom_addr = 0
    for line in cleaned:
        if line.startswith('(') and line.endswith(')'):
            symbols[line[1:-1]] = rom_addr
        else:
            rom_addr += 1

    # Pass 2: generate binary
    next_var = 16
    binary = []
    for line in cleaned:
        if line.startswith('('):
            continue
        if line.startswith('@'):
            val = line[1:]
            if val.isdigit():
                addr = int(val)
            else:
                if val not in symbols:
                    symbols[val] = next_var
                    next_var += 1
                addr = symbols[val]
            binary.append(format(addr & 0x7FFF, '016b'))
        else:
            dest_s, comp_s, jump_s = '', '', ''
            if '=' in line:
                dest_s, line = line.split('=', 1)
            if ';' in line:
                comp_s, jump_s = line.split(';', 1)
            else:
                comp_s = line
            dest_s = dest_s.strip()
            comp_s = comp_s.strip()
            jump_s = jump_s.strip()
            binary.append('111' + _COMP[comp_s] + _DEST[dest_s] + _JUMP[jump_s])

    with open(output_hack, 'w') as f:
        for b in binary:
            f.write(b + '\n')


# ===========================================================================
# CPU EMULATOR
# ===========================================================================

def _sign16(v):
    v = v & 0xFFFF
    return v - 0x10000 if v >= 0x8000 else v


def _alu(comp_bits, d_val, y_val):
    """Execute ALU: 6 control bits (zx,nx,zy,ny,f,no) on x=D, y=A/M."""
    zx = (comp_bits >> 5) & 1
    nx = (comp_bits >> 4) & 1
    zy = (comp_bits >> 3) & 1
    ny = (comp_bits >> 2) & 1
    f  = (comp_bits >> 1) & 1
    no = comp_bits & 1

    x = d_val & 0xFFFF
    y = y_val & 0xFFFF

    if zx: x = 0
    if nx: x = (~x) & 0xFFFF
    if zy: y = 0
    if ny: y = (~y) & 0xFFFF

    if f:
        out = (x + y) & 0xFFFF
    else:
        out = x & y

    if no:
        out = (~out) & 0xFFFF

    return out


def emulate(hack_file, cycles, init_ram=None):
    """Execute Hack binary, return dict of non-zero RAM (signed)."""
    with open(hack_file) as f:
        rom = [int(line.strip(), 2) for line in f if line.strip()]

    ram = [0] * 32768
    if init_ram:
        for addr, val in init_ram.items():
            ram[int(addr)] = val & 0xFFFF

    a_reg = 0
    d_reg = 0
    pc = 0

    for _ in range(cycles):
        if pc >= len(rom):
            a_reg = 0
            pc += 1
            continue

        inst = rom[pc]

        if not (inst & 0x8000):
            # A-instruction
            a_reg = inst & 0x7FFF
            pc += 1
        else:
            # C-instruction: 111a cccccc ddd jjj
            a_bit = (inst >> 12) & 1
            comp  = (inst >> 6) & 0x3F
            dest  = (inst >> 3) & 7
            jump  = inst & 7

            y_val = ram[a_reg & 0x7FFF] if a_bit else a_reg
            result = _alu(comp, d_reg, y_val)

            old_a = a_reg

            if dest & 4:  # A
                a_reg = result
            if dest & 2:  # D
                d_reg = result
            if dest & 1:  # M (use old A as address)
                ram[old_a & 0x7FFF] = result

            # Jump decision based on signed result
            s = _sign16(result)
            do_jump = False
            if jump & 4 and s < 0:
                do_jump = True
            if jump & 2 and s == 0:
                do_jump = True
            if jump & 1 and s > 0:
                do_jump = True

            if do_jump:
                pc = old_a & 0x7FFF
            else:
                pc += 1

    # Return non-zero RAM entries as signed
    out = {}
    for i in range(len(ram)):
        if ram[i] != 0:
            out[i] = _sign16(ram[i])
    return out


# ===========================================================================
# PIPELINE
# ===========================================================================

def run_pipeline(vm_input, cycles, init_ram=None, bootstrap=False):
    """Full pipeline: VM -> ASM -> HACK -> execute -> RAM state."""
    if os.path.isdir(vm_input):
        vm_files = sorted(glob.glob(os.path.join(vm_input, '*.vm')))
        base = os.path.basename(vm_input.rstrip('/'))
        bootstrap = True
    else:
        vm_files = [vm_input]
        base = os.path.splitext(os.path.basename(vm_input))[0]

    with tempfile.TemporaryDirectory() as d:
        asm = os.path.join(d, base + '.asm')
        hack = os.path.join(d, base + '.hack')
        translate_vm(vm_files, asm, bootstrap=bootstrap)
        assemble(asm, hack)
        return emulate(hack, cycles, init_ram=init_ram)


if __name__ == '__main__':
    import json
    if len(sys.argv) < 3:
        print("Usage: hack_pipeline.py <vm_file_or_dir> <cycles> [init_ram_json]")
        sys.exit(1)
    vm_in = sys.argv[1]
    cy = int(sys.argv[2])
    ir = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
    if ir:
        ir = {int(k): int(v) for k, v in ir.items()}
    result = run_pipeline(vm_in, cy, init_ram=ir, bootstrap=os.path.isdir(vm_in))
    print(json.dumps({str(k): v for k, v in sorted(result.items())}, indent=2))
