#!/usr/bin/env python3
"""
Cpu0 Assembler - produces ELF32 big-endian relocatable object files (.o).
Two-pass: first pass collects labels, second pass encodes and emits relocations
for unresolved cross-file references.
"""

import sys
import struct
import re

# ── ELF constants ──────────────────────────────────────────────
ELFCLASS32 = 1
ELFDATA2MSB = 2
EV_CURRENT = 1
ELFOSABI_NONE = 0
ET_REL = 1
EM_CPU0 = 0xC9

SHT_NULL = 0
SHT_PROGBITS = 1
SHT_SYMTAB = 2
SHT_STRTAB = 3
SHT_REL = 9

SHF_ALLOC = 0x2
SHF_EXECINSTR = 0x4

STB_LOCAL = 0
STB_GLOBAL = 1
STT_NOTYPE = 0
STT_SECTION = 3
SHN_UNDEF = 0

R_CPU0_PC24 = 1
R_CPU0_PC16 = 2
R_CPU0_32 = 3

# ── Register map ───────────────────────────────────────────────
REGS = {}
for name, num in [
    ("zero", 0), ("at", 1), ("v0", 2), ("v1", 3),
    ("a0", 4), ("a1", 5), ("t9", 6), ("t0", 7),
    ("t1", 8), ("s0", 9), ("s1", 10), ("gp", 11),
    ("fp", 12), ("sp", 13), ("lr", 14), ("sw", 15),
]:
    REGS[f"${name}"] = num
    REGS[f"${num}"] = num

# ── Instruction table ──────────────────────────────────────────
# mnemonic -> (opcode, format, operand_type)
INSTRUCTIONS = {
    "nop":   (0x00, "L", "none"),
    "ld":    (0x01, "L", "rm"),   "st":    (0x02, "L", "rm"),
    "lb":    (0x03, "L", "rm"),   "lbu":   (0x04, "L", "rm"),
    "sb":    (0x05, "L", "rm"),   "lh":    (0x06, "L", "rm"),
    "lhu":   (0x07, "L", "rm"),   "sh":    (0x08, "L", "rm"),
    "addiu": (0x09, "L", "rri"),
    "andi":  (0x0C, "L", "rri"),  "ori":   (0x0D, "L", "rri"),
    "xori":  (0x0E, "L", "rri"),  "lui":   (0x0F, "L", "ri"),
    "addu":  (0x11, "A", "rrr"),  "subu":  (0x12, "A", "rrr"),
    "add":   (0x13, "A", "rrr"),  "sub":   (0x14, "A", "rrr"),
    "clz":   (0x15, "A", "rr"),   "clo":   (0x16, "A", "rr"),
    "mul":   (0x17, "A", "rrr"),
    "and":   (0x18, "A", "rrr"),  "or":    (0x19, "A", "rrr"),
    "xor":   (0x1A, "A", "rrr"),  "nor":   (0x1B, "A", "rrr"),
    "rol":   (0x1C, "A", "rrc"),  "ror":   (0x1D, "A", "rrc"),
    "shl":   (0x1E, "A", "rrc"),  "shr":   (0x1F, "A", "rrc"),
    "sra":   (0x20, "A", "rrc"),
    "srav":  (0x21, "A", "rrr"),  "shlv":  (0x22, "A", "rrr"),
    "shrv":  (0x23, "A", "rrr"),  "rolv":  (0x24, "A", "rrr"),
    "rorv":  (0x25, "A", "rrr"),
    "slti":  (0x26, "L", "rri"),  "sltiu": (0x27, "L", "rri"),
    "slt":   (0x28, "A", "rrr"),  "sltu":  (0x29, "A", "rrr"),
    "cmp":   (0x2A, "A", "rr"),   "cmpu":  (0x2B, "A", "rr"),
    "jeq":   (0x30, "J", "j"),    "jne":   (0x31, "J", "j"),
    "jlt":   (0x32, "J", "j"),    "jgt":   (0x33, "J", "j"),
    "jle":   (0x34, "J", "j"),    "jge":   (0x35, "J", "j"),
    "jmp":   (0x36, "J", "j"),
    "beq":   (0x37, "L", "rrb"),  "bne":   (0x38, "L", "rrb"),
    "jalr":  (0x39, "A", "jalr"), "bal":   (0x3A, "J", "j"),
    "jsub":  (0x3B, "J", "j"),
    "jr":    (0x3C, "A", "jr"),   "ret":   (0x3C, "A", "jr"),
    "mult":  (0x41, "A", "rr"),   "multu": (0x42, "A", "rr"),
    "div":   (0x43, "A", "rr"),   "divu":  (0x44, "A", "rr"),
    "mfhi":  (0x46, "A", "r"),    "mflo":  (0x47, "A", "r"),
    "mthi":  (0x48, "A", "r"),    "mtlo":  (0x49, "A", "r"),
}


def parse_reg(s):
    s = s.strip().lower()
    if s in REGS:
        return REGS[s]
    raise ValueError(f"Unknown register: {s}")


def parse_imm(s):
    s = s.strip()
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    val = int(s, 16) if s.lower().startswith("0x") else int(s)
    return -val if neg else val


def parse_mem(s):
    m = re.match(r"(-?(?:0[xX][0-9a-fA-F]+|\d+))\(\s*(\$\w+)\s*\)", s.strip())
    if not m:
        raise ValueError(f"Invalid memory operand: {s}")
    return parse_imm(m.group(1)), parse_reg(m.group(2))


def split_operands(text):
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1; cur.append(ch)
        elif ch == ")":
            depth -= 1; cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip()); cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return [p for p in parts if p]


def enc_l(op, ra, rb, cx16):
    return (op << 24) | (ra << 20) | (rb << 16) | (cx16 & 0xFFFF)


def enc_a(op, ra, rb, rc, cx12):
    return (op << 24) | (ra << 20) | (rb << 16) | (rc << 12) | (cx12 & 0xFFF)


def enc_j(op, cx24):
    return (op << 24) | (cx24 & 0xFFFFFF)


def strip_line(line):
    idx = line.find(";")
    return (line[:idx] if idx >= 0 else line).strip()


def parse_source(text):
    result = []
    for raw in text.split("\n"):
        line = strip_line(raw)
        if not line:
            continue
        label = None
        m = re.match(r"^([A-Za-z_]\w*)\s*:", line)
        if m:
            label = m.group(1)
            line = line[m.end():].strip()
        if not line:
            result.append((label, None, None))
            continue
        parts = line.split(None, 1)
        result.append((label, parts[0].lower(), parts[1].strip() if len(parts) > 1 else ""))
    return result


def _align(v, a):
    return (v + a - 1) & ~(a - 1)


def assemble(input_path, output_path):
    with open(input_path) as f:
        text = f.read()

    parsed = parse_source(text)

    # Collect directives
    globals_set = set()
    labels = {}
    instr_list = []
    addr = 0

    for label, token, operand in parsed:
        if label:
            labels[label] = addr
        if token is None:
            continue
        if token.startswith("."):
            if token in (".globl", ".global"):
                globals_set.add(operand.strip())
            continue
        instr_list.append((token, operand, addr))
        addr += 4

    # Encode instructions
    text_data = bytearray()
    relocations = []

    for mnemonic, operand_str, iaddr in instr_list:
        if mnemonic not in INSTRUCTIONS:
            raise ValueError(f"Unknown instruction: {mnemonic} at 0x{iaddr:04X}")

        opcode, fmt, optype = INSTRUCTIONS[mnemonic]
        ops = split_operands(operand_str) if operand_str else []
        word = 0

        if optype == "j":
            target = ops[0].strip()
            if target in labels:
                word = enc_j(opcode, labels[target] - (iaddr + 4))
            else:
                word = enc_j(opcode, 0)
                relocations.append((iaddr, R_CPU0_PC24, target))
        elif optype == "rrb":
            ra, rb = parse_reg(ops[0]), parse_reg(ops[1])
            target = ops[2].strip()
            if target in labels:
                word = enc_l(opcode, ra, rb, labels[target] - (iaddr + 4))
            else:
                word = enc_l(opcode, ra, rb, 0)
                relocations.append((iaddr, R_CPU0_PC16, target))
        elif optype == "none":
            word = enc_l(opcode, 0, 0, 0)
        elif optype == "rm":
            ra = parse_reg(ops[0]); off, rb = parse_mem(ops[1])
            word = enc_l(opcode, ra, rb, off)
        elif optype == "rri":
            word = enc_l(opcode, parse_reg(ops[0]), parse_reg(ops[1]), parse_imm(ops[2]))
        elif optype == "ri":
            word = enc_l(opcode, parse_reg(ops[0]), 0, parse_imm(ops[1]))
        elif optype == "rrr":
            word = enc_a(opcode, parse_reg(ops[0]), parse_reg(ops[1]), parse_reg(ops[2]), 0)
        elif optype == "rr":
            word = enc_a(opcode, parse_reg(ops[0]), parse_reg(ops[1]), 0, 0)
        elif optype == "r":
            word = enc_a(opcode, parse_reg(ops[0]), 0, 0, 0)
        elif optype == "rrc":
            word = enc_a(opcode, parse_reg(ops[0]), parse_reg(ops[1]), 0, parse_imm(ops[2]))
        elif optype == "jr":
            word = enc_a(opcode, parse_reg(ops[0]), 0, 0, 0)
        elif optype == "jalr":
            word = enc_a(opcode, 0, parse_reg(ops[0]), 0, 0)

        text_data += struct.pack(">I", word & 0xFFFFFFFF)

    _write_elf(output_path, text_data, relocations, labels, globals_set)


def _write_elf(path, text_data, relocations, labels, globals_set):
    # ── Build string tables ──
    shstrtab = bytearray(b"\0")
    shstr_off = {}

    def _add_shstr(name):
        shstr_off[name] = len(shstrtab)
        shstrtab.extend(name.encode() + b"\0")

    for n in [".text", ".symtab", ".strtab", ".shstrtab"]:
        _add_shstr(n)
    if relocations:
        _add_shstr(".rel.text")

    strtab = bytearray(b"\0")
    str_off = {"": 0}

    def _add_str(name):
        if name and name not in str_off:
            str_off[name] = len(strtab)
            strtab.extend(name.encode() + b"\0")

    # ── Build symbol table ──
    local_syms = []   # (name, value, shndx, stype)
    global_syms = []

    # Section symbol for .text
    local_syms.append(("", 0, 1, STT_SECTION))

    # Local labels
    for name in sorted(labels, key=labels.get):
        if name not in globals_set:
            _add_str(name)
            local_syms.append((name, labels[name], 1, STT_NOTYPE))

    # Global defined
    for name in sorted(labels, key=labels.get):
        if name in globals_set:
            _add_str(name)
            global_syms.append((name, labels[name], 1, STT_NOTYPE))

    # Undefined externals
    undef = sorted({s for _, _, s in relocations if s not in labels})
    for name in undef:
        _add_str(name)
        global_syms.append((name, 0, SHN_UNDEF, STT_NOTYPE))

    num_locals = 1 + len(local_syms)  # +1 for null entry
    all_syms = [None] + local_syms + global_syms
    sym_idx_map = {}

    symtab = bytearray()
    for i, sym in enumerate(all_syms):
        if i == 0:
            symtab += struct.pack(">IIIBBH", 0, 0, 0, 0, 0, 0)
            continue
        name, val, shndx, stype = sym
        binding = STB_LOCAL if i < num_locals else STB_GLOBAL
        symtab += struct.pack(">IIIBBH",
            str_off.get(name, 0), val, 0,
            (binding << 4) | stype, 0, shndx)
        if name:
            sym_idx_map[name] = i

    # ── Build relocation entries ──
    rel_data = bytearray()
    for offset, rtype, sym_name in relocations:
        sidx = sym_idx_map[sym_name]
        rel_data += struct.pack(">II", offset, (sidx << 8) | rtype)

    # ── Section layout ──
    sections = [
        {"name": "", "type": SHT_NULL, "flags": 0, "data": b"",
         "align": 0, "entsize": 0, "link": 0, "info": 0},
        {"name": ".text", "type": SHT_PROGBITS,
         "flags": SHF_ALLOC | SHF_EXECINSTR, "data": bytes(text_data),
         "align": 4, "entsize": 0, "link": 0, "info": 0},
    ]
    TEXT_IDX = 1

    if relocations:
        REL_IDX = len(sections)
        sections.append({"name": ".rel.text", "type": SHT_REL, "flags": 0,
            "data": bytes(rel_data), "align": 4, "entsize": 8,
            "link": 0, "info": TEXT_IDX})
    else:
        REL_IDX = None

    SYMTAB_IDX = len(sections)
    sections.append({"name": ".symtab", "type": SHT_SYMTAB, "flags": 0,
        "data": bytes(symtab), "align": 4, "entsize": 16,
        "link": 0, "info": num_locals})

    STRTAB_IDX = len(sections)
    sections.append({"name": ".strtab", "type": SHT_STRTAB, "flags": 0,
        "data": bytes(strtab), "align": 1, "entsize": 0, "link": 0, "info": 0})

    SHSTRTAB_IDX = len(sections)
    sections.append({"name": ".shstrtab", "type": SHT_STRTAB, "flags": 0,
        "data": bytes(shstrtab), "align": 1, "entsize": 0, "link": 0, "info": 0})

    # Fix cross-references
    sections[SYMTAB_IDX]["link"] = STRTAB_IDX
    if REL_IDX is not None:
        sections[REL_IDX]["link"] = SYMTAB_IDX

    # Compute offsets
    cur = 52  # ELF header size
    for i, s in enumerate(sections):
        if i == 0:
            s["offset"] = 0; continue
        if s["align"] > 1:
            cur = _align(cur, s["align"])
        s["offset"] = cur
        cur += len(s["data"])

    shoff = _align(cur, 4)

    # ── Write file ──
    with open(path, "wb") as f:
        ident = bytearray(16)
        ident[0:4] = b"\x7fELF"
        ident[4] = ELFCLASS32
        ident[5] = ELFDATA2MSB
        ident[6] = EV_CURRENT
        f.write(bytes(ident))
        f.write(struct.pack(">HHIIIIIHHHHHH",
            ET_REL, EM_CPU0, EV_CURRENT, 0, 0, shoff, 0, 52,
            0, 0, 40, len(sections), SHSTRTAB_IDX))

        for i, s in enumerate(sections):
            if i == 0:
                continue
            pos = f.tell()
            if s["offset"] > pos:
                f.write(b"\0" * (s["offset"] - pos))
            f.write(s["data"])

        pos = f.tell()
        if shoff > pos:
            f.write(b"\0" * (shoff - pos))

        for s in sections:
            f.write(struct.pack(">IIIIIIIIII",
                shstr_off.get(s["name"], 0),
                s["type"], s["flags"], 0,
                s["offset"] if s["type"] != SHT_NULL else 0,
                len(s["data"]), s["link"], s["info"],
                s["align"], s["entsize"]))


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.s> <output.o>", file=sys.stderr)
        sys.exit(1)
    assemble(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
