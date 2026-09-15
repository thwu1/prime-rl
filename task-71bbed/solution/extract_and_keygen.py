#!/usr/bin/env python3
"""
Automated reverse engineering of two VM crackme binaries (alpha and beta),
plus design and implementation of a novel hardened crackme (gamma).

Strategy for alpha/beta:
1. Read the stripped ELF binary
2. Locate the 4-byte XOR decryption key by pattern-matching encrypted bytecode
   against known first-instruction patterns (PUSH_IMM64 + common hash seeds)
3. Decrypt the bytecode
4. Disassemble the bytecode to recover the verification algorithm
5. Extract all cryptographic constants and identify known algorithms
6. Generate a Python keygen replicating the algorithm

Gamma design:
7. Assemble novel bytecode using the discovered ISA with algorithms not found
   in alpha or beta (polynomial rolling hash + Stafford Mix13 + PCG-inspired mixing)
8. Include anti-analysis: two opaque predicates with dead code paths
9. Encrypt with a new XOR key and write gamma.bc + gamma_key.bin
10. Generate keygen_gamma.py and audit.json
"""


import struct
import os
import json

BINARY_ALPHA = '/app/crackme_alpha'
BINARY_BETA = '/app/crackme_beta'

# ============================================================
# VM opcode definitions (discovered through reverse engineering)
# ============================================================

OP_NAMES = {
    0x00: 'NOP',       0x01: 'PUSH_IMM8',  0x02: 'PUSH_IMM64',
    0x03: 'PUSH_REG',  0x04: 'POP_REG',
    0x05: 'ADD',  0x06: 'SUB',  0x07: 'MUL',  0x08: 'XOR',
    0x09: 'AND',  0x0A: 'OR',   0x0B: 'SHR',  0x0C: 'SHL',
    0x0D: 'MOD',  0x0E: 'NOT',  0x0F: 'CMP_EQ', 0x10: 'CMP_LT',
    0x11: 'JMP',  0x12: 'JZ',   0x13: 'JNZ',
    0x14: 'LOAD_INPUT', 0x15: 'INPUT_LEN',
    0x16: 'DUP',  0x17: 'SWAP', 0x18: 'ROTL', 0x19: 'HALT',
    0x1A: 'LOAD_KEY',  0x1B: 'ROTR',
}
OPERAND_SZ = {0x01: 1, 0x02: 8, 0x03: 1, 0x04: 1, 0x11: 2, 0x12: 2, 0x13: 2}
VALID_OPCODES = set(OP_NAMES.keys())

KNOWN_FIRST_CONSTANTS = [
    0xcbf29ce484222325,  # FNV-1a offset basis
    0x1505150515051505,  # DJB2 seed (64-bit extension)
]

KNOWN_CONSTANTS = {
    0xcbf29ce484222325: 'FNV-1a offset basis',
    0x100000001b3:      'FNV-1a prime',
    0xff51afd7ed558ccd: 'MurmurHash3 fmix64 C1',
    0xc4ceb9fe1a85ec53: 'MurmurHash3 fmix64 C2',
    0x9E3779B97F4A7C15: 'Golden ratio (Fibonacci hashing)',
    0x517CC1B727220A95: 'Custom mix multiplier',
    0xBEEFCAFE12345678: 'Custom mix addend',
    0x1505150515051505: 'DJB2 seed (64-bit extension)',
    0xC96C5795D7870F42: 'CRC-64-ECMA polynomial',
    0x2545F4914F6CDD1D: 'xxHash PRIME64_5',
    0x3C6EF372FE94F82B: 'Golden ratio variant addend',
    0x12345678AABBCCDD: 'Fake constant (dead code)',
    0x9988776655443322: 'Fake constant (dead code)',
}


# ============================================================
# Binary analysis functions
# ============================================================

def find_xor_key_and_bytecode(data):
    for pos in range(len(data) - 20):
        key0 = data[pos] ^ 0x02
        for known_const in KNOWN_FIRST_CONSTANTS:
            const_le = struct.pack('<Q', known_const)
            key = [
                key0,
                data[pos + 1] ^ const_le[0],
                data[pos + 2] ^ const_le[1],
                data[pos + 3] ^ const_le[2],
            ]
            ok = True
            for i in range(4, 9):
                if data[pos + i] ^ key[i % 4] != const_le[i - 1]:
                    ok = False
                    break
            if not ok:
                continue
            if pos + 9 < len(data):
                next_op = data[pos + 9] ^ key[9 % 4]
                if next_op in VALID_OPCODES:
                    return key, pos, known_const
    return None, None, None


def decrypt_bytecode(data, offset, key, max_len=4096):
    raw = data[offset:offset + max_len]
    return bytearray(raw[i] ^ key[i % 4] for i in range(len(raw)))


def disassemble(bytecode):
    pc = 0
    instructions = []
    halts = 0
    while pc < len(bytecode) and halts < 3:
        op = bytecode[pc]
        if op not in OP_NAMES:
            break
        instr = {'pc': pc, 'op': op, 'name': OP_NAMES[op]}
        pc += 1
        sz = OPERAND_SZ.get(op, 0)
        if sz == 1:
            instr['operand'] = bytecode[pc]; pc += 1
        elif sz == 2:
            instr['operand'] = struct.unpack_from('<H', bytecode, pc)[0]; pc += 2
        elif sz == 8:
            instr['operand'] = struct.unpack_from('<Q', bytecode, pc)[0]; pc += 8
        instructions.append(instr)
        if op == 0x19:
            halts += 1
    return instructions


def analyze_binary(path):
    print(f"\n{'='*60}\n[*] Analyzing {path}\n{'='*60}")
    with open(path, 'rb') as f:
        data = f.read()
    key, bc_offset, first_const = find_xor_key_and_bytecode(data)
    assert key is not None, f"Could not find XOR key in {path}"
    print(f"    XOR key: {' '.join(f'{b:02x}' for b in key)}")
    print(f"    Bytecode offset: {hex(bc_offset)}")
    bytecode = decrypt_bytecode(data, bc_offset, key)
    instructions = disassemble(bytecode)
    print(f"    Disassembled {len(instructions)} instructions")
    constants = []
    for ins in instructions:
        if ins['op'] == 0x02 and 'operand' in ins:
            constants.append(ins['operand'])
    algo_type = 'alpha' if first_const == 0xcbf29ce484222325 else \
                'beta' if first_const == 0x1505150515051505 else 'unknown'
    anti_analysis = []
    for i, ins in enumerate(instructions):
        if (ins['name'] == 'CMP_EQ' and i + 1 < len(instructions) and
                instructions[i + 1]['name'] == 'JNZ' and
                i >= 2 and instructions[i - 1]['name'] == 'PUSH_IMM8' and
                instructions[i - 2]['name'] == 'MUL'):
            anti_analysis.append('opaque predicate')
            anti_analysis.append('dead code path')
            break
    has_shl5 = any(
        ins['name'] == 'SHL' and i > 0 and
        instructions[i-1]['name'] == 'PUSH_IMM8' and
        instructions[i-1]['operand'] == 5
        for i, ins in enumerate(instructions)
    )
    return {
        'path': path, 'algo_type': algo_type, 'xor_key': key,
        'bc_offset': bc_offset, 'first_const': first_const,
        'constants': constants, 'anti_analysis': anti_analysis,
        'has_shl5': has_shl5, 'num_instructions': len(instructions),
    }


# ============================================================
# Keygen generators for alpha and beta
# ============================================================

def generate_keygen_alpha():
    return '''#!/usr/bin/env python3
"""Keygen for crackme alpha — FNV-1a + MurmurHash3 fmix64 + custom mixing."""
import sys

MASK = 0xFFFFFFFFFFFFFFFF

def keygen(username):
    h = 0xcbf29ce484222325
    for b in username.encode('ascii'):
        h ^= b
        h = (h * 0x100000001b3) & MASK
    h ^= h >> 33
    h = (h * 0xff51afd7ed558ccd) & MASK
    h ^= h >> 33
    h = (h * 0xc4ceb9fe1a85ec53) & MASK
    h ^= h >> 33
    h ^= 0x9e3779b97f4a7c15
    h = ((h << 17) | (h >> 47)) & MASK
    h = (h * 0x517cc1b727220a95) & MASK
    h ^= h >> 27
    h = ((h >> 13) | (h << 51)) & MASK
    h = (h + 0xbeefcafe12345678) & MASK
    h ^= h >> 31
    return format(h, 'x')

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <username>", file=sys.stderr)
        sys.exit(1)
    print(keygen(sys.argv[1]))
'''


def generate_keygen_beta():
    return '''#!/usr/bin/env python3
"""Keygen for crackme beta — DJB2a (64-bit) + xxHash/CRC-inspired mixing."""
import sys

MASK = 0xFFFFFFFFFFFFFFFF

def keygen(username):
    h = 0x1505150515051505
    for b in username.encode('ascii'):
        h = ((((h << 5) & MASK) + h) & MASK) ^ b
    h ^= 0xc96c5795d7870f42
    h = ((h << 23) | (h >> 41)) & MASK
    h = (h * 0x2545f4914f6cdd1d) & MASK
    h ^= h >> 29
    h = ((h >> 19) | (h << 45)) & MASK
    h = (h + 0x3c6ef372fe94f82b) & MASK
    h ^= h >> 31
    return format(h, 'x')

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <username>", file=sys.stderr)
        sys.exit(1)
    print(keygen(sys.argv[1]))
'''


def generate_keygen_universal():
    return '''#!/usr/bin/env python3
"""Universal keygen — auto-detects crackme variant from binary contents."""
import sys, struct

MASK = 0xFFFFFFFFFFFFFFFF

VARIANT_SEEDS = {
    0xcbf29ce484222325: 'alpha',
    0x1505150515051505: 'beta',
}

def detect_variant(binary_path):
    with open(binary_path, 'rb') as f:
        data = f.read()
    for pos in range(len(data) - 20):
        key0 = data[pos] ^ 0x02
        for seed, variant in VARIANT_SEEDS.items():
            const_le = struct.pack('<Q', seed)
            key = [key0, data[pos+1] ^ const_le[0],
                   data[pos+2] ^ const_le[1], data[pos+3] ^ const_le[2]]
            ok = True
            for i in range(4, 9):
                if data[pos+i] ^ key[i % 4] != const_le[i-1]:
                    ok = False; break
            if ok:
                nxt = data[pos+9] ^ key[9 % 4]
                if 0 <= nxt <= 0x1B:
                    return variant
    raise RuntimeError(f"Could not detect variant for {binary_path}")

def keygen_alpha(username):
    h = 0xcbf29ce484222325
    for b in username.encode('ascii'):
        h ^= b; h = (h * 0x100000001b3) & MASK
    h ^= h >> 33; h = (h * 0xff51afd7ed558ccd) & MASK
    h ^= h >> 33; h = (h * 0xc4ceb9fe1a85ec53) & MASK
    h ^= h >> 33; h ^= 0x9e3779b97f4a7c15
    h = ((h << 17) | (h >> 47)) & MASK
    h = (h * 0x517cc1b727220a95) & MASK; h ^= h >> 27
    h = ((h >> 13) | (h << 51)) & MASK
    h = (h + 0xbeefcafe12345678) & MASK; h ^= h >> 31
    return format(h, 'x')

def keygen_beta(username):
    h = 0x1505150515051505
    for b in username.encode('ascii'):
        h = ((((h << 5) & MASK) + h) & MASK) ^ b
    h ^= 0xc96c5795d7870f42
    h = ((h << 23) | (h >> 41)) & MASK
    h = (h * 0x2545f4914f6cdd1d) & MASK; h ^= h >> 29
    h = ((h >> 19) | (h << 45)) & MASK
    h = (h + 0x3c6ef372fe94f82b) & MASK; h ^= h >> 31
    return format(h, 'x')

KEYGENS = {'alpha': keygen_alpha, 'beta': keygen_beta}

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <binary_path> <username>", file=sys.stderr)
        sys.exit(1)
    variant = detect_variant(sys.argv[1])
    print(KEYGENS[variant](sys.argv[2]))
'''


# ============================================================
# Gamma bytecode assembler
# ============================================================

# Opcode constants for assembler
_NOP=0x00; _PUSH8=0x01; _PUSH64=0x02; _PUSH_R=0x03; _POP_R=0x04
_ADD=0x05; _SUB=0x06; _MUL=0x07; _XOR=0x08; _AND=0x09; _OR=0x0A
_SHR=0x0B; _SHL=0x0C; _MOD=0x0D; _NOT=0x0E; _CMP_EQ=0x0F; _CMP_LT=0x10
_JMP=0x11; _JZ=0x12; _JNZ=0x13; _LOAD_INP=0x14; _INP_LEN=0x15
_DUP=0x16; _SWAP=0x17; _ROTL=0x18; _HALT=0x19; _LOAD_KEY=0x1A; _ROTR=0x1B

R0, R1, R2, R3, R4, R5, R6, R7 = range(8)


class Asm:
    """Bytecode assembler for the VM ISA."""
    def __init__(self):
        self.buf = bytearray()
        self.labels = {}
        self.fixups = []

    def _b(self, *args):
        for b in args:
            self.buf.append(b & 0xFF)

    def _u16(self, v):
        self.buf.extend(struct.pack('<H', v & 0xFFFF))

    def _u64(self, v):
        self.buf.extend(struct.pack('<Q', v & 0xFFFFFFFFFFFFFFFF))

    def label(self, name):
        self.labels[name] = len(self.buf)

    def push8(self, v):  self._b(_PUSH8, v)
    def push64(self, v): self._b(_PUSH64); self._u64(v)
    def push_r(self, r): self._b(_PUSH_R, r)
    def pop_r(self, r):  self._b(_POP_R, r)
    def add(self):       self._b(_ADD)
    def sub(self):       self._b(_SUB)
    def mul(self):       self._b(_MUL)
    def xor(self):       self._b(_XOR)
    def and_(self):      self._b(_AND)
    def or_(self):       self._b(_OR)
    def shr(self):       self._b(_SHR)
    def shl(self):       self._b(_SHL)
    def mod(self):       self._b(_MOD)
    def not_(self):      self._b(_NOT)
    def cmp_eq(self):    self._b(_CMP_EQ)
    def cmp_lt(self):    self._b(_CMP_LT)
    def dup(self):       self._b(_DUP)
    def swap(self):      self._b(_SWAP)
    def rotl(self):      self._b(_ROTL)
    def rotr(self):      self._b(_ROTR)
    def halt(self):      self._b(_HALT)
    def load_key(self):  self._b(_LOAD_KEY)
    def load_inp(self):  self._b(_LOAD_INP)
    def inp_len(self):   self._b(_INP_LEN)
    def nop(self):       self._b(_NOP)

    def jmp(self, lbl):
        self._b(_JMP); self.fixups.append((len(self.buf), lbl)); self._u16(0)

    def jz(self, lbl):
        self._b(_JZ); self.fixups.append((len(self.buf), lbl)); self._u16(0)

    def jnz(self, lbl):
        self._b(_JNZ); self.fixups.append((len(self.buf), lbl)); self._u16(0)

    def build(self):
        for pos, lbl in self.fixups:
            struct.pack_into('<H', self.buf, pos, self.labels[lbl])
        return bytes(self.buf)


def generate_gamma_bytecode():
    """Assemble and encrypt gamma bytecode.

    Algorithm (all constants distinct from alpha/beta):
      Phase 1: Polynomial rolling hash
        seed  = 0x62B821B5F35A4C17 (custom)
        prime = 0x13A10D71F1E053CB (custom)
        h = seed; for each byte: h = h * prime + byte

      Anti-analysis: opaque predicate (11*11=121 != 120) + dead code

      Phase 2: Stafford Mix13 bijective finalizer
        h ^= h >> 30; h *= 0xBF58476D1CE4E5B9
        h ^= h >> 27; h *= 0x94D049BB133111EB
        h ^= h >> 31

      Anti-analysis: second opaque predicate (5+5=10, 10*3=30 != 31) + dead code

      Phase 3: PCG-inspired rotation mixing
        h = rotl(h, 11); h *= 0xD6E8FEB86659FD93
        h ^= h >> 23; h = rotr(h, 7)
        h += 0x4A7330CFBB3C8A43; h ^= h >> 29

      Compare with serial key.
    """
    GAMMA_XOR_KEY = [0x93, 0x27, 0xAB, 0x5E]
    a = Asm()

    # === Phase 1: Polynomial rolling hash ===
    a.push64(0x62B821B5F35A4C17)   # custom seed
    a.pop_r(R2)                     # R2 = h
    a.push8(0)
    a.pop_r(R3)                     # R3 = i = 0
    a.inp_len()
    a.pop_r(R4)                     # R4 = len

    a.label('loop')
    a.push_r(R3)
    a.push_r(R4)
    a.cmp_lt()
    a.jz('loop_end')

    # h = h * prime + byte
    a.push_r(R2)
    a.push64(0x13A10D71F1E053CB)   # polynomial prime
    a.mul()
    a.push_r(R3)
    a.load_inp()
    a.add()
    a.pop_r(R2)

    a.push_r(R3)
    a.push8(1)
    a.add()
    a.pop_r(R3)
    a.jmp('loop')

    a.label('loop_end')

    # === Anti-analysis: opaque predicate 1 ===
    # 11 * 11 = 121, cmp_eq 120 -> 0, jnz not taken
    a.push8(11)
    a.push8(11)
    a.mul()
    a.push8(120)
    a.cmp_eq()
    a.jnz('fake1')
    a.jmp('phase2')

    a.label('fake1')
    # Dead code: decoy algorithm
    a.push_r(R2)
    a.push64(0xDEADBEEFCAFEBABE)
    a.xor()
    a.pop_r(R2)
    a.push_r(R2)
    a.push64(0xFEEDFACE0BADF00D)
    a.mul()
    a.pop_r(R2)
    a.push_r(R2)
    a.load_key()
    a.cmp_eq()
    a.pop_r(R0)
    a.halt()

    a.label('phase2')

    # === Phase 2: Stafford Mix13 ===
    # h ^= h >> 30
    a.push_r(R2); a.push_r(R2); a.push8(30); a.shr(); a.xor(); a.pop_r(R2)
    # h *= 0xBF58476D1CE4E5B9
    a.push_r(R2); a.push64(0xBF58476D1CE4E5B9); a.mul(); a.pop_r(R2)
    # h ^= h >> 27
    a.push_r(R2); a.push_r(R2); a.push8(27); a.shr(); a.xor(); a.pop_r(R2)
    # h *= 0x94D049BB133111EB
    a.push_r(R2); a.push64(0x94D049BB133111EB); a.mul(); a.pop_r(R2)
    # h ^= h >> 31
    a.push_r(R2); a.push_r(R2); a.push8(31); a.shr(); a.xor(); a.pop_r(R2)

    # === Anti-analysis: opaque predicate 2 ===
    # (5+5)*3 = 30, cmp_eq 31 -> 0, jnz not taken
    a.push8(5)
    a.push8(5)
    a.add()
    a.push8(3)
    a.mul()
    a.push8(31)
    a.cmp_eq()
    a.jnz('fake2')
    a.jmp('phase3')

    a.label('fake2')
    # Dead code: different decoy
    a.push_r(R2)
    a.push64(0x1122334455667788)
    a.add()
    a.pop_r(R2)
    a.push_r(R2)
    a.load_key()
    a.cmp_eq()
    a.pop_r(R0)
    a.halt()

    a.label('phase3')

    # === Phase 3: PCG-inspired rotation mixing ===
    # h = rotl(h, 11)
    a.push_r(R2); a.push8(11); a.rotl(); a.pop_r(R2)
    # h *= 0xD6E8FEB86659FD93
    a.push_r(R2); a.push64(0xD6E8FEB86659FD93); a.mul(); a.pop_r(R2)
    # h ^= h >> 23
    a.push_r(R2); a.push_r(R2); a.push8(23); a.shr(); a.xor(); a.pop_r(R2)
    # h = rotr(h, 7)
    a.push_r(R2); a.push8(7); a.rotr(); a.pop_r(R2)
    # h += 0x4A7330CFBB3C8A43
    a.push_r(R2); a.push64(0x4A7330CFBB3C8A43); a.add(); a.pop_r(R2)
    # h ^= h >> 29
    a.push_r(R2); a.push_r(R2); a.push8(29); a.shr(); a.xor(); a.pop_r(R2)

    # === Compare with serial key ===
    a.push_r(R2)
    a.load_key()
    a.cmp_eq()
    a.pop_r(R0)
    a.halt()

    bytecode = a.build()
    encrypted = bytes(b ^ GAMMA_XOR_KEY[i % 4] for i, b in enumerate(bytecode))
    return encrypted, bytes(GAMMA_XOR_KEY)


def generate_keygen_gamma():
    return '''#!/usr/bin/env python3
"""Keygen for gamma — polynomial hash + Stafford Mix13 + PCG-inspired mixing."""
import sys

MASK = 0xFFFFFFFFFFFFFFFF

def keygen(username):
    # Phase 1: Polynomial rolling hash
    h = 0x62B821B5F35A4C17
    for b in username.encode('ascii'):
        h = ((h * 0x13A10D71F1E053CB) + b) & MASK

    # Phase 2: Stafford Mix13
    h ^= h >> 30
    h = (h * 0xBF58476D1CE4E5B9) & MASK
    h ^= h >> 27
    h = (h * 0x94D049BB133111EB) & MASK
    h ^= h >> 31

    # Phase 3: PCG-inspired rotation mixing
    h = ((h << 11) | (h >> 53)) & MASK
    h = (h * 0xD6E8FEB86659FD93) & MASK
    h ^= h >> 23
    h = ((h >> 7) | (h << 57)) & MASK
    h = (h + 0x4A7330CFBB3C8A43) & MASK
    h ^= h >> 29

    return format(h, 'x')

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <username>", file=sys.stderr)
        sys.exit(1)
    print(keygen(sys.argv[1]))
'''


# ============================================================
# Audit generation
# ============================================================

def generate_audit(analysis_alpha, analysis_beta):
    alpha_consts = set(analysis_alpha['constants'])
    alpha_algos = []
    if 0xcbf29ce484222325 in alpha_consts:
        alpha_algos.append('FNV-1a (64-bit)')
    if 0xff51afd7ed558ccd in alpha_consts or 0xc4ceb9fe1a85ec53 in alpha_consts:
        alpha_algos.append('MurmurHash3 fmix64 finalizer')

    beta_algos = []
    if analysis_beta['has_shl5']:
        beta_algos.append('DJB2a (64-bit XOR variant)')
    beta_consts = set(analysis_beta['constants'])
    if 0x2545F4914F6CDD1D in beta_consts:
        beta_algos.append('xxHash-inspired mixing')
    if 0xC96C5795D7870F42 in beta_consts:
        beta_algos.append('CRC-64-ECMA constant')

    return {
        "schemes": {
            "alpha": {
                "key_derivation_stages": 3,
                "algorithms_used": alpha_algos,
                "anti_analysis_techniques": analysis_alpha['anti_analysis'],
                "avalanche_quality": "good",
                "estimated_re_hours": 3.0,
            },
            "beta": {
                "key_derivation_stages": 2,
                "algorithms_used": beta_algos,
                "anti_analysis_techniques": analysis_beta['anti_analysis'],
                "avalanche_quality": "moderate",
                "estimated_re_hours": 1.5,
            },
            "gamma": {
                "key_derivation_stages": 3,
                "algorithms_used": [
                    "Polynomial rolling hash (custom prime)",
                    "Stafford Mix13 bijective finalizer",
                    "PCG-inspired rotation mixing",
                ],
                "anti_analysis_techniques": [
                    "opaque predicate (arithmetic)",
                    "dead code path with decoy constants",
                    "second opaque predicate (compound arithmetic)",
                    "second dead code path with alternative decoy",
                ],
                "avalanche_quality": "excellent",
                "estimated_re_hours": 5.0,
            },
        },
        "ranking": ["gamma", "alpha", "beta"],
        "ranking_justification": (
            "Gamma is the strongest scheme because it combines three high-quality "
            "mixing stages—polynomial hash with a large prime for initial diffusion, "
            "Stafford Mix13 (a provably bijective finalizer with near-perfect avalanche), "
            "and PCG-inspired rotation mixing with both left and right rotations—plus "
            "two independent opaque predicates creating multiple dead code paths that "
            "confuse static analysis. Alpha ranks second with its three-phase pipeline "
            "(FNV-1a + MurmurHash3 fmix64 + custom mixing) and single opaque predicate, "
            "but FNV-1a's XOR-then-multiply pattern is well-documented and the MurmurHash3 "
            "constants are widely recognized. Beta is weakest with only two stages (DJB2a + "
            "single mixing pass), no anti-analysis techniques, and DJB2's characteristic "
            "shift-5-plus-add pattern being one of the most recognizable hash signatures. "
            "Beta also has fewer mixing operations, reducing overall diffusion quality."
        ),
        "attack_vectors": {
            "alpha": [
                "FNV-1a offset basis 0xcbf29ce484222325 is a well-known constant",
                "MurmurHash3 fmix64 constants are catalogued in hash identification databases",
                "Single opaque predicate uses simple arithmetic (7*3=21) easily solvable",
                "XOR key recovery via known-plaintext on PUSH_IMM64 opcode",
            ],
            "beta": [
                "DJB2 shift-5-plus-add is trivially recognizable from disassembly",
                "No anti-analysis techniques — linear control flow",
                "Only two mixing stages provide less resistance to differential analysis",
                "xxHash PRIME64_5 constant is publicly documented",
                "CRC-64-ECMA polynomial is well-known",
                "XOR key recovery via known-plaintext on PUSH_IMM64 opcode",
            ],
            "gamma": [
                "XOR key recovery via known-plaintext on PUSH_IMM64 opcode (inherent to VM design)",
                "Polynomial hash constants could potentially be identified through coefficient analysis",
            ],
        },
    }


# ============================================================
# Main
# ============================================================

def main():
    # 1. Analyze both binaries
    analysis_alpha = analyze_binary(BINARY_ALPHA)
    analysis_beta = analyze_binary(BINARY_BETA)
    assert analysis_alpha['algo_type'] == 'alpha'
    assert analysis_beta['algo_type'] == 'beta'

    # 2. Generate keygens for alpha and beta
    print("[*] Generating keygen_alpha.py...")
    with open('/app/keygen_alpha.py', 'w') as f:
        f.write(generate_keygen_alpha())
    os.chmod('/app/keygen_alpha.py', 0o755)

    print("[*] Generating keygen_beta.py...")
    with open('/app/keygen_beta.py', 'w') as f:
        f.write(generate_keygen_beta())
    os.chmod('/app/keygen_beta.py', 0o755)

    print("[*] Generating keygen_universal.py...")
    with open('/app/keygen_universal.py', 'w') as f:
        f.write(generate_keygen_universal())
    os.chmod('/app/keygen_universal.py', 0o755)

    # 3. Generate gamma scheme
    print("[*] Assembling gamma bytecode...")
    gamma_bc, gamma_key = generate_gamma_bytecode()
    with open('/app/gamma.bc', 'wb') as f:
        f.write(gamma_bc)
    with open('/app/gamma_key.bin', 'wb') as f:
        f.write(gamma_key)
    print(f"    Bytecode: {len(gamma_bc)} bytes, key: {gamma_key.hex()}")

    print("[*] Generating keygen_gamma.py...")
    with open('/app/keygen_gamma.py', 'w') as f:
        f.write(generate_keygen_gamma())
    os.chmod('/app/keygen_gamma.py', 0o755)

    # 4. Generate audit
    print("[*] Generating audit.json...")
    audit = generate_audit(analysis_alpha, analysis_beta)
    with open('/app/audit.json', 'w') as f:
        json.dump(audit, f, indent=2)

    print("[*] All deliverables generated successfully.")


if __name__ == '__main__':
    main()
