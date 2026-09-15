#!/usr/bin/env python3
"""
Generate microcode ROM puzzle files for the 8086-inspired reverse-engineering task.

Inspired by reenigne's work extracting and disassembling 8086/8088 microcode from
die photographs, this script creates a scrambled microcode ROM that must be decoded
by determining a bit-column permutation using known instruction patterns from a
"patent excerpt" (analogous to US patent 4363091 used for the real 8086).

Output formats:
  - rom.bin: raw binary (128 x 3 bytes, big-endian 24-bit words)
  - microcode.db: SQLite database with translation table, patent words, encodings
  - field_spec.txt: describes the field layout and permutation model

The microcode format is a simplified 24-bit micro-operation word:
  src  [3:0]   - 4 bits - source operand
  dst  [7:4]   - 4 bits - destination operand
  alu  [11:8]  - 4 bits - ALU operation
  ctrl [14:12] - 3 bits - control flow
  imm  [23:15] - 9 bits - immediate/jump target
"""

import json
import os
import sqlite3

# --- Field Encodings ---

AX, BX, CX, DX, SI, DI, SP, BP = 0, 1, 2, 3, 4, 5, 6, 7
TEMP, IMM, FLAGS, PC, ZERO, MEM, ONES, SEL = 8, 9, 10, 11, 12, 13, 14, 15

REG_NAMES = {
    0: "AX", 1: "BX", 2: "CX", 3: "DX", 4: "SI", 5: "DI", 6: "SP", 7: "BP",
    8: "TEMP", 9: "IMM", 10: "FLAGS", 11: "PC", 12: "ZERO", 13: "MEM", 14: "ONES", 15: "SEL"
}

MOV, ADD, SUB, AND, OR, XOR, SHL, SHR = 0, 1, 2, 3, 4, 5, 6, 7
CMP, INC, DEC, NOT, NEG, TEST, ADC, NOP = 8, 9, 10, 11, 12, 13, 14, 15

ALU_NAMES = {
    0: "MOV", 1: "ADD", 2: "SUB", 3: "AND", 4: "OR", 5: "XOR", 6: "SHL", 7: "SHR",
    8: "CMP", 9: "INC", 10: "DEC", 11: "NOT", 12: "NEG", 13: "TEST", 14: "ADC", 15: "NOP"
}

NEXT, END, JZ, JNZ, JMP = 0, 1, 2, 3, 4
CTRL_NAMES = {0: "NEXT", 1: "END", 2: "JZ", 3: "JNZ", 4: "JMP", 5: "RSVD5", 6: "RSVD6", 7: "HALT"}

# --- Bit Permutation ---
PERM = [17, 3, 11, 23, 7, 14, 0, 20, 9, 22, 5, 13, 1, 19, 8, 16, 12, 4, 21, 6, 15, 2, 10, 18]


def encode_uop(src, dst, alu, ctrl, imm):
    word = (src & 0xF) | ((dst & 0xF) << 4) | ((alu & 0xF) << 8) | ((ctrl & 0x7) << 12) | ((imm & 0x1FF) << 15)
    return word


def decode_uop(word):
    src = word & 0xF
    dst = (word >> 4) & 0xF
    alu = (word >> 8) & 0xF
    ctrl = (word >> 12) & 0x7
    imm = (word >> 15) & 0x1FF
    return src, dst, alu, ctrl, imm


def scramble(word):
    result = 0
    for i in range(24):
        if word & (1 << PERM[i]):
            result |= (1 << i)
    return result


def unscramble(word):
    result = 0
    for i in range(24):
        if word & (1 << i):
            result |= (1 << PERM[i])
    return result


# --- Microcode ROM Definition ---
ROM_SIZE = 128
ROM = [0] * ROM_SIZE

ROM[0] = encode_uop(ZERO, ZERO, NOP, END, 0)
ROM[1] = encode_uop(IMM, SEL, MOV, END, 0)
ROM[2] = encode_uop(IMM, TEMP, MOV, NEXT, 0)
ROM[3] = encode_uop(TEMP, SEL, ADD, END, 0)
ROM[4] = encode_uop(IMM, TEMP, MOV, NEXT, 0)
ROM[5] = encode_uop(TEMP, SEL, SUB, END, 0)
ROM[6] = encode_uop(IMM, TEMP, MOV, NEXT, 0)
ROM[7] = encode_uop(TEMP, SEL, AND, END, 0)
ROM[8] = encode_uop(IMM, TEMP, MOV, NEXT, 0)
ROM[9] = encode_uop(TEMP, SEL, OR, END, 0)
ROM[10] = encode_uop(IMM, TEMP, MOV, NEXT, 0)
ROM[11] = encode_uop(TEMP, SEL, XOR, END, 0)
ROM[12] = encode_uop(IMM, TEMP, MOV, NEXT, 0)
ROM[13] = encode_uop(TEMP, SEL, CMP, END, 0)
ROM[14] = encode_uop(IMM, TEMP, MOV, NEXT, 0)
ROM[15] = encode_uop(TEMP, SEL, TEST, END, 0)
ROM[16] = encode_uop(SEL, SEL, INC, END, 0)
ROM[17] = encode_uop(SEL, SEL, DEC, END, 0)
ROM[18] = encode_uop(SEL, SEL, NOT, END, 0)
ROM[19] = encode_uop(SEL, SEL, NEG, END, 0)
ROM[20] = encode_uop(SEL, SEL, SHL, END, 0)
ROM[21] = encode_uop(SEL, SEL, SHR, END, 0)
ROM[22] = encode_uop(SP, SP, DEC, NEXT, 0)
ROM[23] = encode_uop(SP, TEMP, MOV, NEXT, 0)
ROM[24] = encode_uop(SEL, MEM, MOV, END, 0)
ROM[25] = encode_uop(SP, TEMP, MOV, NEXT, 0)
ROM[26] = encode_uop(MEM, SEL, MOV, NEXT, 0)
ROM[27] = encode_uop(SP, SP, INC, END, 0)
ROM[28] = encode_uop(FLAGS, TEMP, MOV, NEXT, 0)
ROM[29] = encode_uop(IMM, PC, ADD, END, 0)
ROM[30] = encode_uop(FLAGS, TEMP, MOV, NEXT, 0)
ROM[31] = encode_uop(IMM, PC, ADD, END, 0)
ROM[32] = encode_uop(IMM, PC, ADD, END, 0)
ROM[33] = encode_uop(SP, SP, DEC, NEXT, 0)
ROM[34] = encode_uop(SP, TEMP, MOV, NEXT, 0)
ROM[35] = encode_uop(PC, MEM, MOV, NEXT, 0)
ROM[36] = encode_uop(IMM, PC, MOV, END, 0)
ROM[37] = encode_uop(SP, TEMP, MOV, NEXT, 0)
ROM[38] = encode_uop(MEM, PC, MOV, NEXT, 0)
ROM[39] = encode_uop(SP, SP, INC, END, 0)
ROM[40] = encode_uop(DI, TEMP, MOV, NEXT, 0)
ROM[41] = encode_uop(AX, MEM, MOV, NEXT, 0)
ROM[42] = encode_uop(DI, DI, INC, END, 0)
# REP STOSW - BUGGY: ROM has JMP 44 at addr 49, patent says JMP 43
ROM[43] = encode_uop(ZERO, CX, CMP, JZ, 51)
ROM[44] = encode_uop(DI, TEMP, MOV, NEXT, 0)
ROM[45] = encode_uop(AX, MEM, MOV, NEXT, 0)
ROM[46] = encode_uop(DI, DI, INC, NEXT, 0)
ROM[47] = encode_uop(DI, DI, INC, NEXT, 0)
ROM[48] = encode_uop(CX, CX, DEC, NEXT, 0)
ROM[49] = encode_uop(ZERO, ZERO, NOP, JMP, 44)  # BUG: should be 43
ROM[50] = encode_uop(ZERO, ZERO, NOP, NEXT, 0)
ROM[51] = encode_uop(ZERO, ZERO, NOP, END, 0)
ROM[52] = encode_uop(IMM, TEMP, MOV, NEXT, 0)
ROM[53] = encode_uop(TEMP, SEL, ADC, END, 0)
ROM[54] = encode_uop(AX, SEL, MOV, END, 0)
ROM[55] = encode_uop(SEL, AX, MOV, END, 0)
ROM[56] = encode_uop(SEL, AX, ADD, END, 0)
ROM[57] = encode_uop(SEL, AX, SUB, END, 0)
ROM[58] = encode_uop(IMM, TEMP, MOV, NEXT, 0)
ROM[59] = encode_uop(MEM, SEL, MOV, END, 0)
ROM[60] = encode_uop(IMM, TEMP, MOV, NEXT, 0)
ROM[61] = encode_uop(SEL, MEM, MOV, END, 0)
ROM[62] = encode_uop(CX, CX, DEC, NEXT, 0)
ROM[63] = encode_uop(ZERO, CX, CMP, JZ, 66)
ROM[64] = encode_uop(IMM, TEMP, MOV, NEXT, 0)
ROM[65] = encode_uop(TEMP, PC, ADD, END, 0)
ROM[66] = encode_uop(ZERO, ZERO, NOP, END, 0)
ROM[67] = encode_uop(AX, TEMP, MOV, NEXT, 0)
ROM[68] = encode_uop(SEL, AX, MOV, NEXT, 0)
ROM[69] = encode_uop(ZERO, DX, MOV, NEXT, 0)
ROM[70] = encode_uop(TEMP, DX, ADD, NEXT, 0)
ROM[71] = encode_uop(AX, AX, SHL, NEXT, 0)
ROM[72] = encode_uop(ZERO, ZERO, NOP, END, 0)
ROM[73] = encode_uop(AX, TEMP, MOV, NEXT, 0)
ROM[74] = encode_uop(DX, AX, MOV, NEXT, 0)
ROM[75] = encode_uop(TEMP, DX, MOV, NEXT, 0)
ROM[76] = encode_uop(SEL, TEMP, MOV, NEXT, 0)
ROM[77] = encode_uop(TEMP, AX, SUB, NEXT, 0)
ROM[78] = encode_uop(ZERO, ZERO, NOP, END, 0)
ROM[79] = encode_uop(BX, TEMP, MOV, NEXT, 0)
ROM[80] = encode_uop(SI, TEMP, ADD, NEXT, 0)
ROM[81] = encode_uop(IMM, TEMP, ADD, NEXT, 0)
ROM[82] = encode_uop(MEM, SEL, MOV, END, 0)
ROM[83] = encode_uop(BP, TEMP, MOV, NEXT, 0)
ROM[84] = encode_uop(DI, TEMP, ADD, NEXT, 0)
ROM[85] = encode_uop(MEM, AX, MOV, END, 0)
ROM[86] = encode_uop(AX, TEMP, MOV, NEXT, 0)
ROM[87] = encode_uop(SEL, AX, MOV, NEXT, 0)
ROM[88] = encode_uop(TEMP, SEL, MOV, END, 0)
ROM[89] = encode_uop(FLAGS, TEMP, MOV, NEXT, 0)
ROM[90] = encode_uop(TEMP, AX, AND, END, 0)
ROM[91] = encode_uop(AX, FLAGS, MOV, END, 0)
ROM[92] = encode_uop(SP, TEMP, MOV, NEXT, 0)
ROM[93] = encode_uop(MEM, PC, MOV, NEXT, 0)
ROM[94] = encode_uop(SP, SP, INC, NEXT, 0)
ROM[95] = encode_uop(SP, SP, INC, END, 0)
ROM[96] = encode_uop(FLAGS, TEMP, MOV, NEXT, 0)
ROM[97] = encode_uop(SP, SP, DEC, NEXT, 0)
ROM[98] = encode_uop(SP, TEMP, MOV, NEXT, 0)
ROM[99] = encode_uop(FLAGS, MEM, MOV, NEXT, 0)
ROM[100] = encode_uop(SP, SP, DEC, NEXT, 0)
ROM[101] = encode_uop(PC, TEMP, MOV, NEXT, 0)
ROM[102] = encode_uop(TEMP, MEM, MOV, NEXT, 0)
ROM[103] = encode_uop(IMM, TEMP, MOV, NEXT, 0)
ROM[104] = encode_uop(TEMP, PC, SHL, NEXT, 0)
ROM[105] = encode_uop(MEM, PC, MOV, END, 0)
ROM[106] = encode_uop(ZERO, AX, MOV, NEXT, 0)
ROM[107] = encode_uop(ZERO, BX, MOV, NEXT, 0)
ROM[108] = encode_uop(ZERO, CX, MOV, NEXT, 0)
ROM[109] = encode_uop(ZERO, DX, MOV, NEXT, 0)
ROM[110] = encode_uop(ONES, PC, MOV, NEXT, 0)
ROM[111] = encode_uop(ZERO, FLAGS, MOV, END, 0)
ROM[112] = encode_uop(ZERO, ZERO, NOP, 7, 0)
ROM[113] = encode_uop(DX, BP, XOR, JNZ, 100)
ROM[114] = encode_uop(AX, BX, ADD, NEXT, 0)
ROM[115] = encode_uop(BX, CX, SUB, NEXT, 0)
ROM[116] = encode_uop(CX, DX, AND, END, 0)
ROM[117] = encode_uop(DX, SI, OR, NEXT, 0)
ROM[118] = encode_uop(SI, DI, XOR, NEXT, 0)
ROM[119] = encode_uop(DI, SP, SHR, END, 0)
ROM[120] = encode_uop(AX, BX, NEG, JMP, 144)
ROM[121] = encode_uop(FLAGS, AX, MOV, NEXT, 0)
ROM[122] = encode_uop(PC, BX, MOV, NEXT, 0)
ROM[123] = encode_uop(TEMP, CX, ADD, END, 0)
ROM[124] = encode_uop(MEM, DX, SUB, NEXT, 0)
ROM[125] = encode_uop(SP, SI, SHR, JZ, 31)
ROM[126] = encode_uop(BX, DX, NOT, JMP, 257)
ROM[127] = encode_uop(CX, SP, ADC, JNZ, 129)

# --- Translation Table ---
TRANS_SIZE = 64
TRANS = [0] * TRANS_SIZE
TRANS[0x00] = 0;   TRANS[0x01] = 1;   TRANS[0x02] = 2;   TRANS[0x03] = 4
TRANS[0x04] = 6;   TRANS[0x05] = 8;   TRANS[0x06] = 10;  TRANS[0x07] = 12
TRANS[0x08] = 14;  TRANS[0x09] = 16;  TRANS[0x0A] = 17;  TRANS[0x0B] = 18
TRANS[0x0C] = 19;  TRANS[0x0D] = 20;  TRANS[0x0E] = 21;  TRANS[0x0F] = 22
TRANS[0x10] = 25;  TRANS[0x11] = 28;  TRANS[0x12] = 30;  TRANS[0x13] = 32
TRANS[0x14] = 33;  TRANS[0x15] = 37;  TRANS[0x16] = 40;  TRANS[0x17] = 43
TRANS[0x18] = 52;  TRANS[0x19] = 54;  TRANS[0x1A] = 55;  TRANS[0x1B] = 56
TRANS[0x1C] = 57;  TRANS[0x1D] = 58;  TRANS[0x1E] = 60;  TRANS[0x1F] = 62
TRANS[0x20] = 67;  TRANS[0x21] = 73;  TRANS[0x22] = 79;  TRANS[0x23] = 83
TRANS[0x24] = 86;  TRANS[0x25] = 89;  TRANS[0x26] = 91;  TRANS[0x27] = 92
TRANS[0x28] = 96;  TRANS[0x29] = 106; TRANS[0x2A] = 112

MNEMONICS = {
    0x00: "NOP", 0x01: "MOV SEL, IMM", 0x02: "ADD SEL, IMM",
    0x03: "SUB SEL, IMM", 0x04: "AND SEL, IMM", 0x05: "OR SEL, IMM",
    0x06: "XOR SEL, IMM", 0x07: "CMP SEL, IMM", 0x08: "TEST SEL, IMM",
    0x09: "INC SEL", 0x0A: "DEC SEL", 0x0B: "NOT SEL",
    0x0C: "NEG SEL", 0x0D: "SHL SEL, 1", 0x0E: "SHR SEL, 1",
    0x0F: "PUSH SEL", 0x10: "POP SEL", 0x11: "JZ rel",
    0x12: "JNZ rel", 0x13: "JMP rel", 0x14: "CALL",
    0x15: "RET", 0x16: "STOSW", 0x17: "REP STOSW",
    0x18: "ADC SEL, IMM", 0x19: "MOV SEL, AX", 0x1A: "MOV AX, SEL",
    0x1B: "ADD AX, SEL", 0x1C: "SUB AX, SEL", 0x1D: "LOAD SEL, [IMM]",
    0x1E: "STORE [IMM], SEL", 0x1F: "LOOP", 0x20: "MUL setup",
    0x21: "DIV setup", 0x22: "EA calc (BX+SI+disp)", 0x23: "EA calc (BP+DI)",
    0x24: "XCHG AX, SEL", 0x25: "SAHF", 0x26: "LAHF",
    0x27: "RET FAR", 0x28: "INT handler", 0x29: "RESET", 0x2A: "HLT",
}

# --- Verify permutation fingerprints ---

KNOWN_ADDRS = [0, 1, 3, 5, 16, 43, 44, 46, 63, 106, 110, 113, 120, 125, 126, 127]


def verify_fingerprints(known_addrs, rom):
    fingerprints = {}
    for bit in range(24):
        fp = tuple((rom[addr] >> bit) & 1 for addr in known_addrs)
        if fp in fingerprints.values():
            for b2, fp2 in fingerprints.items():
                if fp2 == fp:
                    return False, bit, b2
        fingerprints[bit] = fp
    return True, None, None


ok, b1, b2 = verify_fingerprints(KNOWN_ADDRS, ROM)
if not ok:
    raise RuntimeError(f"Fingerprint collision between bits {b1} and {b2}!")


def find_minimal_known(all_addrs, rom):
    selected = []
    for addr in all_addrs:
        selected.append(addr)
        fps = {}
        unique = True
        for bit in range(24):
            fp = tuple((rom[a] >> bit) & 1 for a in selected)
            if fp in fps.values():
                unique = False
                break
            fps[bit] = fp
        if unique:
            return selected
    return selected


PATENT_ADDRS = find_minimal_known(KNOWN_ADDRS, ROM)

# --- Output Functions ---


def write_binary_rom(path):
    """Write scrambled ROM as raw binary: 128 x 3 bytes, big-endian 24-bit."""
    with open(path, 'wb') as f:
        for addr in range(ROM_SIZE):
            s = scramble(ROM[addr])
            f.write(bytes([(s >> 16) & 0xFF, (s >> 8) & 0xFF, s & 0xFF]))


def create_database(db_path):
    """Create SQLite database with all reference data."""
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE registers (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE alu_ops (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE ctrl_ops (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE field_layout (
        field_name TEXT PRIMARY KEY,
        bit_lo INTEGER NOT NULL, bit_hi INTEGER NOT NULL,
        width INTEGER NOT NULL, description TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE translations (
        opcode INTEGER PRIMARY KEY,
        start_addr INTEGER NOT NULL, mnemonic TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE patent_words (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        addr INTEGER NOT NULL,
        logical_hex TEXT NOT NULL, logical_binary TEXT NOT NULL,
        src INTEGER NOT NULL, src_name TEXT NOT NULL,
        dst INTEGER NOT NULL, dst_name TEXT NOT NULL,
        alu INTEGER NOT NULL, alu_name TEXT NOT NULL,
        ctrl INTEGER NOT NULL, ctrl_name TEXT NOT NULL,
        imm INTEGER NOT NULL,
        section TEXT NOT NULL, note TEXT
    )''')
    c.execute('''CREATE TABLE notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT NOT NULL, content TEXT NOT NULL
    )''')

    for k, v in REG_NAMES.items():
        c.execute("INSERT INTO registers VALUES (?,?)", (k, v))
    for k, v in ALU_NAMES.items():
        c.execute("INSERT INTO alu_ops VALUES (?,?)", (k, v))
    for k, v in CTRL_NAMES.items():
        c.execute("INSERT INTO ctrl_ops VALUES (?,?)", (k, v))

    fields = [
        ('src', 0, 3, 4, 'source operand register/special'),
        ('dst', 4, 7, 4, 'destination operand register/special'),
        ('alu', 8, 11, 4, 'ALU operation selector'),
        ('ctrl', 12, 14, 3, 'control flow type'),
        ('imm', 15, 23, 9, 'immediate value or jump target address'),
    ]
    for f in fields:
        c.execute("INSERT INTO field_layout VALUES (?,?,?,?,?)", f)

    for opc in range(TRANS_SIZE):
        mnem = MNEMONICS.get(opc, f"ALIAS_NOP_{opc:02X}")
        c.execute("INSERT INTO translations VALUES (?,?,?)", (opc, TRANS[opc], mnem))

    def insert_patent_word(addr, word, section, note=None):
        s, d, a, ct, im = decode_uop(word)
        c.execute(
            "INSERT INTO patent_words (addr,logical_hex,logical_binary,"
            "src,src_name,dst,dst_name,alu,alu_name,ctrl,ctrl_name,imm,section,note) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (addr, f"0x{word:06X}", f"{word:024b}",
             s, REG_NAMES[s], d, REG_NAMES[d],
             a, ALU_NAMES[a], ct, CTRL_NAMES[ct], im, section, note))

    # Known instruction listings (actual ROM values, used for permutation cracking)
    basic_addrs = [0, 1, 2, 3, 4, 5, 16, 17]
    for addr in basic_addrs:
        insert_patent_word(addr, ROM[addr], 'known')

    # REP STOSW patent version (CORRECT values per patent specification)
    patent_rep_stosw = [
        (43, encode_uop(ZERO, CX, CMP, JZ, 51)),
        (44, encode_uop(DI, TEMP, MOV, NEXT, 0)),
        (45, encode_uop(AX, MEM, MOV, NEXT, 0)),
        (46, encode_uop(DI, DI, INC, NEXT, 0)),
        (47, encode_uop(DI, DI, INC, NEXT, 0)),
        (48, encode_uop(CX, CX, DEC, NEXT, 0)),
        (49, encode_uop(ZERO, ZERO, NOP, JMP, 43)),  # CORRECT: JMP 43
        (50, encode_uop(ZERO, ZERO, NOP, NEXT, 0)),
        (51, encode_uop(ZERO, ZERO, NOP, END, 0)),
    ]
    for addr, word in patent_rep_stosw:
        note = "CORRECT per patent: JMP target should be 43" if addr == 49 else None
        insert_patent_word(addr, word, 'patent_rep_stosw', note)

    # Additional known words for permutation cracking
    extra_addrs = [a for a in PATENT_ADDRS
                   if a not in basic_addrs and a not in range(43, 52)]
    for addr in extra_addrs:
        insert_patent_word(addr, ROM[addr], 'known')

    # Notes
    c.execute("INSERT INTO notes (topic, content) VALUES (?,?)",
              ("REP STOSW errata",
               "The patent documents specific microcode for the REP STOSW instruction "
               "(opcode 0x17, starting at the address given in the translations table). "
               "The actual ROM implementation may differ from the patent listing. "
               "Query patent_words WHERE section='patent_rep_stosw' for the patent version, "
               "then compare against the decoded ROM to identify discrepancies."))
    c.execute("INSERT INTO notes (topic, content) VALUES (?,?)",
              ("Bit permutation",
               "The rom.bin file stores bits in physical (die) order. A fixed "
               "bit-column permutation was applied during fabrication: "
               "physical_bit[i] = logical_bit[P[i]]. Use the known patent words "
               "(section='known') to determine P by comparing their logical bit "
               "patterns against the corresponding scrambled patterns in rom.bin."))
    c.execute("INSERT INTO notes (topic, content) VALUES (?,?)",
              ("Binary ROM format",
               "rom.bin contains 128 entries of 3 bytes each (384 bytes total). "
               "Each 24-bit word is stored in big-endian byte order. "
               "Word at address N starts at byte offset 3*N. "
               "Use xxd, od, or similar tools to inspect the raw binary."))

    conn.commit()
    conn.close()


def write_field_spec(path):
    with open(path, 'w') as f:
        f.write("MICROCODE FIELD SPECIFICATION\n")
        f.write("=" * 50 + "\n\n")
        f.write("Each micro-operation is a 24-bit word with the following\n")
        f.write("LOGICAL field layout (bit 0 = LSB):\n\n")
        f.write("  Bits [3:0]   - src  (4 bits) - source operand\n")
        f.write("  Bits [7:4]   - dst  (4 bits) - destination operand\n")
        f.write("  Bits [11:8]  - alu  (4 bits) - ALU operation\n")
        f.write("  Bits [14:12] - ctrl (3 bits) - control flow\n")
        f.write("  Bits [23:15] - imm  (9 bits) - immediate/jump target\n\n")
        f.write("WARNING: The file rom.bin stores bits in PHYSICAL (die)\n")
        f.write("order, which differs from the logical order above.\n")
        f.write("A fixed bit-column permutation was applied during ROM\n")
        f.write("fabrication. You must determine this permutation to\n")
        f.write("decode the microcode.\n\n")
        f.write("The permutation maps physical bit positions to logical\n")
        f.write("bit positions. Specifically, for each 24-bit word:\n")
        f.write("  physical_bit[i] = logical_bit[P[i]]\n")
        f.write("where P is the unknown permutation of {0..23}.\n\n")
        f.write("Cross-reference data is stored in microcode.db (SQLite).\n")
        f.write("Query the patent_words, translations, registers, alu_ops,\n")
        f.write("and ctrl_ops tables for encoding references.\n")


def write_expected_answers(path):
    answers = {}
    answers["permutation"] = PERM
    query_addrs = [10, 25, 49, 75, 100]
    answers["decoded_words"] = {}
    for addr in query_addrs:
        answers["decoded_words"][str(addr)] = f"0x{ROM[addr]:06X}"
    end_count = sum(1 for w in ROM if ((w >> 12) & 0x7) == END)
    answers["end_count"] = end_count
    alu_hist = {}
    for name in ALU_NAMES.values():
        alu_hist[name] = 0
    for w in ROM:
        alu_op = (w >> 8) & 0xF
        alu_hist[ALU_NAMES[alu_op]] += 1
    answers["alu_histogram"] = alu_hist
    buggy_word = ROM[49]
    _, _, _, _, buggy_imm = decode_uop(buggy_word)
    answers["bug"] = {
        "address": 49, "field": "imm",
        "actual_value": buggy_imm, "correct_value": 43,
    }
    pairs = set()
    for w in ROM:
        s = w & 0xF
        d = (w >> 4) & 0xF
        pairs.add((s, d))
    answers["unique_register_pairs"] = len(pairs)
    # Compute expected CFG edge count
    edge_count = 0
    for addr in range(ROM_SIZE):
        ctrl = (ROM[addr] >> 12) & 0x7
        if ctrl == NEXT:
            edge_count += 1
        elif ctrl in (JZ, JNZ):
            edge_count += 2
        elif ctrl == JMP:
            edge_count += 1
    answers["cfg_edge_count"] = edge_count

    with open(path, 'w') as f:
        json.dump(answers, f, indent=2)


# --- Main ---

if __name__ == "__main__":
    outdir = "/app"
    os.makedirs(outdir, exist_ok=True)

    write_binary_rom(os.path.join(outdir, "rom.bin"))
    create_database(os.path.join(outdir, "microcode.db"))
    write_field_spec(os.path.join(outdir, "field_spec.txt"))
    write_expected_answers(os.path.join(outdir, ".expected_answers.json"))

    # Verify round-trip
    for addr in range(ROM_SIZE):
        scrambled = scramble(ROM[addr])
        recovered = unscramble(scrambled)
        assert recovered == ROM[addr], f"Round-trip failed at addr {addr}"

    # Verify binary file
    with open(os.path.join(outdir, "rom.bin"), 'rb') as f:
        data = f.read()
    assert len(data) == ROM_SIZE * 3
    for addr in range(ROM_SIZE):
        b = data[addr*3:addr*3+3]
        val = (b[0] << 16) | (b[1] << 8) | b[2]
        assert val == scramble(ROM[addr]), f"Binary verify failed at addr {addr}"

    print(f"Generated {ROM_SIZE} microcode words")
    print(f"Patent provides {len(PATENT_ADDRS)} known decoded words")
    print(f"Binary ROM: {ROM_SIZE * 3} bytes")
    print("All files written to /app/")
    print("Verification: PASSED")
