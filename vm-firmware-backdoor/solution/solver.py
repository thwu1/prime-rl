#!/usr/bin/env python3
"""
Solver for OOO VM firmware security audit & hardening challenge.

Strategy:
1. Parse ooovm.c to learn the 33-opcode Field Code ISA.
2. Build a disassembler from the opcode table.
3. Load and disassemble all three firmware binaries (alpha, beta, gamma).

4. Alpha analysis:
   - Identify backdoor: LI16 0x1020/0x1021, LDM, LI8 <magic>, TEQ → JZA/JMA
   - Extract magic prefix bytes and stored key from init_key's LI8/LI16/STM pattern
   - Craft exploit token: magic prefix + zero padding

5. Beta analysis:
   - Find PRNG seed: LI8 <seed>, LI16 0x1200, STM
   - Extract LCG constants from LDM/LI8/ML2/LI8/AD2/LI8 0xFF/AN2
   - Find XOR target from XR2, LI8 <target>, TEQ
   - Compute deterministic keystream, derive valid token

6. Gamma analysis:
   - Find key bytes: LI8 <val>, LI16 0x1100+i, STM
   - Find weights: LI8 <val>, LI16 0x1108+i, STM
   - Identify checksum comparison: weighted sum compared via LI16 <target>, TEQ
   - Compute collision: adjust two bytes by weight ratios to maintain sum invariant

7. Evaluate: CVSS 3.1 scoring, comparative risk ranking

8. Create patches:
   - Alpha: redirect backdoor JMA target to no_bd label
   - Gamma: construct new firmware with byte-by-byte comparison
"""

import struct
import subprocess
import json

# ---- Opcode table (from ooovm.c FC_* defines) ----

OPCODES = {
    0x00: ("NOP", 0), 0x01: ("LI8", 1), 0x02: ("LI16", 2),
    0x03: ("DRP", 0), 0x04: ("CPY", 0), 0x05: ("SWP", 0),
    0x06: ("INC", 0), 0x07: ("DEC", 0), 0x08: ("AD2", 0),
    0x09: ("SB2", 0), 0x0A: ("ML2", 0), 0x0B: ("DV2", 0),
    0x0C: ("RM2", 0), 0x0D: ("AN2", 0), 0x0E: ("OR2", 0),
    0x0F: ("XR2", 0), 0x10: ("NT1", 0), 0x11: ("SL2", 0),
    0x12: ("SR2", 0), 0x13: ("TEQ", 0), 0x14: ("TLT", 0),
    0x15: ("TGT", 0), 0x16: ("JMA", 2), 0x17: ("JZA", 2),
    0x18: ("JNA", 2), 0x19: ("CLA", 2), 0x1A: ("RBK", 0),
    0x1B: ("LDM", 0), 0x1C: ("STM", 0), 0x1D: ("RDI", 0),
    0x1E: ("WRO", 0), 0x1F: ("HLT", 0), 0x20: ("OVR", 0),
}


def disassemble(code):
    instructions = []
    pc = 0
    while pc < len(code):
        addr = pc
        op = code[pc]
        pc += 1
        if op in OPCODES:
            name, nargs = OPCODES[op]
            if nargs == 1:
                if pc >= len(code):
                    break
                arg = code[pc]
                pc += 1
                instructions.append((addr, name, arg))
            elif nargs == 2:
                if pc + 1 >= len(code):
                    break
                arg = code[pc] | (code[pc + 1] << 8)
                pc += 2
                instructions.append((addr, name, arg))
            else:
                instructions.append((addr, name, None))
        else:
            instructions.append((addr, f"UNK_{op:02x}", None))
    return instructions


def load_firmware(path):
    with open(path, "rb") as f:
        data = f.read()
    assert data[:4] == b"OOOV", f"Bad magic in {path}"
    entry = struct.unpack("<H", data[6:8])[0]
    code = data[8:]
    return data, entry, code


def run_vm(firmware, token):
    r = subprocess.run(
        ["/app/ooovm", firmware],
        input=token.encode(),
        capture_output=True,
        timeout=5,
    )
    return r.stdout.decode()


# =================================================================
# Alpha analysis: find backdoor and legitimate key
# =================================================================

def analyze_alpha(instructions):
    # Find magic bytes: LI16 0x1020/0x1021, LDM, LI8 <val>, TEQ
    magic_bytes = []
    for i in range(len(instructions) - 3):
        i0, i1, i2, i3 = instructions[i:i + 4]
        if (i0[1] == "LI16" and i0[2] in (0x1020, 0x1021)
                and i1[1] == "LDM"
                and i2[1] == "LI8"
                and i3[1] == "TEQ"):
            magic_bytes.append(i2[2])

    # Find backdoor JMA (preceded by JZA + TEQ)
    backdoor_jma = None
    no_bd_addr = None
    for i in range(2, len(instructions)):
        if (instructions[i][1] == "JMA"
                and instructions[i - 1][1] == "JZA"
                and instructions[i - 2][1] == "TEQ"):
            backdoor_jma = instructions[i]
            no_bd_addr = instructions[i - 1][2]
            break

    # Find key from LI8 <val>, LI16 0x11xx, STM
    key_bytes = {}
    for i in range(len(instructions) - 2):
        if (instructions[i][1] == "LI8"
                and instructions[i + 1][1] == "LI16"
                and instructions[i + 2][1] == "STM"):
            addr = instructions[i + 1][2]
            if 0x1100 <= addr <= 0x1107:
                key_bytes[addr - 0x1100] = instructions[i][2]

    return magic_bytes, backdoor_jma, no_bd_addr, key_bytes


# =================================================================
# Beta analysis: find PRNG parameters
# =================================================================

def analyze_beta(instructions):
    seed = None
    lcg_a = None
    lcg_b = None
    xor_target = None

    # Find seed: LI8 <seed>, LI16 0x1200, STM
    for i in range(len(instructions) - 2):
        if (instructions[i][1] == "LI8"
                and instructions[i + 1][1] == "LI16"
                and instructions[i + 1][2] == 0x1200
                and instructions[i + 2][1] == "STM"):
            seed = instructions[i][2]
            break

    # Find LCG: LI16 0x1200, LDM, LI8 <A>, ML2, LI8 <B>, AD2, LI8 0xFF, AN2
    for i in range(len(instructions) - 7):
        if (instructions[i][1] == "LI16" and instructions[i][2] == 0x1200
                and instructions[i + 1][1] == "LDM"
                and instructions[i + 2][1] == "LI8"
                and instructions[i + 3][1] == "ML2"
                and instructions[i + 4][1] == "LI8"
                and instructions[i + 5][1] == "AD2"
                and instructions[i + 6][1] == "LI8"
                and instructions[i + 6][2] == 0xFF
                and instructions[i + 7][1] == "AN2"):
            lcg_a = instructions[i + 2][2]
            lcg_b = instructions[i + 4][2]
            break

    # Find XOR target: XR2, LI8 <target>, TEQ
    for i in range(len(instructions) - 2):
        if (instructions[i][1] == "XR2"
                and instructions[i + 1][1] == "LI8"
                and instructions[i + 2][1] == "TEQ"):
            xor_target = instructions[i + 1][2]
            break

    return seed, lcg_a, lcg_b, xor_target


# =================================================================
# Gamma analysis: find key, weights, and checksum target
# =================================================================

def analyze_gamma(instructions):
    # Find key bytes: LI8 <val>, LI16 0x1100+i, STM
    key_bytes = {}
    for i in range(len(instructions) - 2):
        if (instructions[i][1] == "LI8"
                and instructions[i + 1][1] == "LI16"
                and instructions[i + 2][1] == "STM"):
            addr = instructions[i + 1][2]
            if 0x1100 <= addr <= 0x1107:
                key_bytes[addr - 0x1100] = instructions[i][2]

    # Find weights: LI8 <val>, LI16 0x1108+i, STM
    weights = {}
    for i in range(len(instructions) - 2):
        if (instructions[i][1] == "LI8"
                and instructions[i + 1][1] == "LI16"
                and instructions[i + 2][1] == "STM"):
            addr = instructions[i + 1][2]
            if 0x1108 <= addr <= 0x110F:
                weights[addr - 0x1108] = instructions[i][2]

    # Find target checksum: LI16 <val>, TEQ, JZA pattern
    # Exclude values in known memory address ranges
    target = None
    for i in range(len(instructions) - 2):
        if (instructions[i][1] == "LI16"
                and instructions[i + 1][1] == "TEQ"
                and instructions[i + 2][1] == "JZA"):
            val = instructions[i][2]
            # Skip known memory/code addresses
            if 0x0000 <= val <= 0x0300:  # code addresses
                continue
            if 0x1000 <= val <= 0x2000:  # data addresses
                continue
            target = val

    return key_bytes, weights, target


def compute_gamma_collision(key, weights):
    """Find an 8-byte input != key with the same weighted checksum mod 65536."""
    exploit = list(key)

    # Adjust bytes 0 and 1: d0*w0 + d1*w1 = 0 (mod 65536)
    # d0 = -w1, d1 = +w0 => (-w1)*w0 + w0*w1 = 0
    w0, w1 = weights[0], weights[1]

    # Try d0 = -w1, d1 = +w0
    if 0 <= exploit[0] - w1 and exploit[1] + w0 <= 255:
        exploit[0] -= w1
        exploit[1] += w0
    elif exploit[0] + w1 <= 255 and 0 <= exploit[1] - w0:
        exploit[0] += w1
        exploit[1] -= w0
    else:
        # Try other byte pairs
        found = False
        for a in range(8):
            for b in range(a + 1, 8):
                wa, wb = weights[a], weights[b]
                if 0 <= exploit[a] - wb and exploit[b] + wa <= 255:
                    exploit[a] -= wb
                    exploit[b] += wa
                    found = True
                    break
                elif exploit[a] + wb <= 255 and 0 <= exploit[b] - wa:
                    exploit[a] += wb
                    exploit[b] -= wa
                    found = True
                    break
            if found:
                break

    return exploit


# =================================================================
# Firmware builder for gamma patch
# =================================================================

class FirmwareBuilder:
    """Build OOOV firmware from raw Field Code bytecode."""

    def __init__(self):
        self.code = bytearray()
        self.labels = {}
        self.fixups = []

    def pos(self):
        return len(self.code)

    def emit(self, *bs):
        for b in bs:
            self.code.append(b & 0xFF)

    def emit16(self, v):
        self.emit(v & 0xFF, (v >> 8) & 0xFF)

    def label(self, name):
        self.labels[name] = self.pos()

    def ref(self, name):
        if name in self.labels:
            self.emit16(self.labels[name])
        else:
            self.fixups.append((self.pos(), name))
            self.emit16(0)

    def resolve(self):
        for off, name in self.fixups:
            addr = self.labels[name]
            self.code[off] = addr & 0xFF
            self.code[off + 1] = (addr >> 8) & 0xFF

    def build(self, entry="main"):
        self.resolve()
        ep = self.labels.get(entry, 0)
        return b"OOOV" + struct.pack("<HH", 1, ep) + bytes(self.code)

    def pstr(self, s):
        for c in s:
            self.emit(0x01, ord(c), 0x1E)  # LI8 <char>, WRO


def create_gamma_patch(key_bytes):
    """Create a hardened gamma firmware with byte-by-byte comparison."""
    f = FirmwareBuilder()

    # Print banner (same as original)
    f.label("main")
    f.pstr("OOO Auth Module Gamma v1.7\nToken: ")

    # Read 16 hex chars into mem[0x1000..0x100F]
    f.emit(0x01, 0)  # LI8 0
    f.label("rd")
    f.emit(0x04)  # CPY
    f.emit(0x01, 16)  # LI8 16
    f.emit(0x13)  # TEQ
    f.emit(0x18)  # JNA
    f.ref("rd_done")
    f.emit(0x1D)  # RDI
    f.emit(0x20)  # OVR
    f.emit(0x02)  # LI16
    f.emit16(0x1000)
    f.emit(0x08)  # AD2
    f.emit(0x1C)  # STM
    f.emit(0x06)  # INC
    f.emit(0x16)  # JMA
    f.ref("rd")
    f.label("rd_done")
    f.emit(0x03)  # DRP

    # Convert hex pairs to bytes at mem[0x1020..0x1027]
    f.emit(0x01, 0)  # LI8 0
    f.label("cv")
    f.emit(0x04)  # CPY
    f.emit(0x01, 8)  # LI8 8
    f.emit(0x13)  # TEQ
    f.emit(0x18)  # JNA
    f.ref("cv_done")
    # High nibble
    f.emit(0x04)  # CPY
    f.emit(0x01, 2)  # LI8 2
    f.emit(0x0A)  # ML2
    f.emit(0x02)  # LI16
    f.emit16(0x1000)
    f.emit(0x08)  # AD2
    f.emit(0x1B)  # LDM
    f.emit(0x19)  # CLA
    f.ref("h2n")
    f.emit(0x01, 4)  # LI8 4
    f.emit(0x11)  # SL2
    # Low nibble
    f.emit(0x20)  # OVR
    f.emit(0x01, 2)  # LI8 2
    f.emit(0x0A)  # ML2
    f.emit(0x02)  # LI16
    f.emit16(0x1001)
    f.emit(0x08)  # AD2
    f.emit(0x1B)  # LDM
    f.emit(0x19)  # CLA
    f.ref("h2n")
    f.emit(0x0E)  # OR2
    # Store byte
    f.emit(0x20)  # OVR
    f.emit(0x02)  # LI16
    f.emit16(0x1020)
    f.emit(0x08)  # AD2
    f.emit(0x1C)  # STM
    f.emit(0x06)  # INC
    f.emit(0x16)  # JMA
    f.ref("cv")
    f.label("cv_done")
    f.emit(0x03)  # DRP

    # Initialize key at 0x1100..0x1107
    f.emit(0x19)  # CLA
    f.ref("init_key")

    # Byte-by-byte comparison (SECURE — replaces checksum)
    f.emit(0x01, 0)  # LI8 0 (counter)
    f.label("vl")
    f.emit(0x04)  # CPY
    f.emit(0x01, 8)  # LI8 8
    f.emit(0x13)  # TEQ
    f.emit(0x18)  # JNA
    f.ref("auth_ok")
    # Load input[i]
    f.emit(0x04)  # CPY
    f.emit(0x02)  # LI16
    f.emit16(0x1020)
    f.emit(0x08)  # AD2
    f.emit(0x1B)  # LDM
    # Load key[i]
    f.emit(0x20)  # OVR
    f.emit(0x02)  # LI16
    f.emit16(0x1100)
    f.emit(0x08)  # AD2
    f.emit(0x1B)  # LDM
    # Compare
    f.emit(0x13)  # TEQ
    f.emit(0x17)  # JZA
    f.ref("denied")
    f.emit(0x06)  # INC
    f.emit(0x16)  # JMA
    f.ref("vl")

    f.label("auth_ok")
    f.emit(0x03)  # DRP
    f.pstr("\nAUTHENTICATED\n")
    f.emit(0x1F)  # HLT

    f.label("denied")
    f.emit(0x03)  # DRP
    f.pstr("\nDENIED\n")
    f.emit(0x1F)  # HLT

    # h2n subroutine: hex char to nibble value
    f.label("h2n")
    f.emit(0x04)  # CPY
    f.emit(0x01, 0x3A)  # LI8 0x3A
    f.emit(0x14)  # TLT
    f.emit(0x17)  # JZA
    f.ref("h2n_a")
    f.emit(0x01, 0x30)  # LI8 0x30
    f.emit(0x09)  # SB2
    f.emit(0x1A)  # RBK
    f.label("h2n_a")
    f.emit(0x04)  # CPY
    f.emit(0x01, 0x61)  # LI8 0x61
    f.emit(0x14)  # TLT
    f.emit(0x17)  # JZA
    f.ref("h2n_l")
    f.emit(0x01, 0x37)  # LI8 0x37
    f.emit(0x09)  # SB2
    f.emit(0x1A)  # RBK
    f.label("h2n_l")
    f.emit(0x01, 0x57)  # LI8 0x57
    f.emit(0x09)  # SB2
    f.emit(0x1A)  # RBK

    # init_key subroutine: store key bytes
    f.label("init_key")
    for i, k in enumerate(key_bytes):
        f.emit(0x01, k)  # LI8 key[i]
        f.emit(0x02)  # LI16
        f.emit16(0x1100 + i)
        f.emit(0x1C)  # STM
    f.emit(0x1A)  # RBK

    return f.build()


# =================================================================
# Main solver
# =================================================================

def main():
    # ===== Analyze Alpha Firmware =====
    alpha_data, alpha_entry, alpha_code = load_firmware("/app/auth_alpha.bin")
    alpha_inst = disassemble(alpha_code)
    print(f"Alpha: {len(alpha_inst)} instructions disassembled")

    magic_bytes, backdoor_jma, no_bd_addr, key_bytes = analyze_alpha(alpha_inst)
    assert len(magic_bytes) == 2, f"Expected 2 magic bytes, got {len(magic_bytes)}"
    assert backdoor_jma is not None, "Backdoor JMA not found"
    assert len(key_bytes) == 8, f"Expected 8 key bytes, got {len(key_bytes)}"

    alpha_key = bytes([key_bytes[i] for i in range(8)])
    alpha_legit = alpha_key.hex()
    alpha_exploit = bytes(magic_bytes + [0] * 6).hex()

    print(f"Alpha magic prefix: {[hex(b) for b in magic_bytes]}")
    print(f"Alpha legit token: {alpha_legit}")
    print(f"Alpha exploit token: {alpha_exploit}")

    out = run_vm("/app/auth_alpha.bin", alpha_exploit)
    assert "AUTHENTICATED" in out, f"Alpha exploit failed: {out}"
    print("Alpha exploit verified.")

    # ===== Analyze Beta Firmware =====
    beta_data, beta_entry, beta_code = load_firmware("/app/auth_beta.bin")
    beta_inst = disassemble(beta_code)
    print(f"\nBeta: {len(beta_inst)} instructions disassembled")

    seed, lcg_a, lcg_b, xor_target = analyze_beta(beta_inst)
    assert seed is not None, "PRNG seed not found"
    assert lcg_a is not None, "LCG multiplier not found"
    assert lcg_b is not None, "LCG increment not found"
    assert xor_target is not None, "XOR target not found"

    print(f"Beta PRNG: seed=0x{seed:02x}, a={lcg_a}, b={lcg_b}")
    print(f"Beta XOR target: 0x{xor_target:02x}")

    # Compute PRNG keystream
    state = seed
    keystream = []
    for _ in range(8):
        state = (state * lcg_a + lcg_b) & 0xFF
        keystream.append(state)

    beta_exploit = bytes([k ^ xor_target for k in keystream]).hex()
    print(f"Beta keystream: {[hex(k) for k in keystream]}")
    print(f"Beta exploit token: {beta_exploit}")

    out = run_vm("/app/auth_beta.bin", beta_exploit)
    assert "AUTHENTICATED" in out, f"Beta exploit failed: {out}"
    print("Beta exploit verified.")

    # ===== Analyze Gamma Firmware =====
    gamma_data, gamma_entry, gamma_code = load_firmware("/app/auth_gamma.bin")
    gamma_inst = disassemble(gamma_code)
    print(f"\nGamma: {len(gamma_inst)} instructions disassembled")

    gamma_key_map, gamma_weight_map, gamma_target = analyze_gamma(gamma_inst)
    assert len(gamma_key_map) == 8, f"Expected 8 key bytes, got {len(gamma_key_map)}"
    assert len(gamma_weight_map) == 8, f"Expected 8 weights, got {len(gamma_weight_map)}"
    assert gamma_target is not None, "Checksum target not found"

    gamma_key = [gamma_key_map[i] for i in range(8)]
    gamma_weights = [gamma_weight_map[i] for i in range(8)]
    gamma_legit = bytes(gamma_key).hex()

    print(f"Gamma key: {[hex(b) for b in gamma_key]}")
    print(f"Gamma weights: {gamma_weights}")
    print(f"Gamma target checksum: {gamma_target} (0x{gamma_target:04x})")

    # Verify: key checksum should equal target
    computed = sum(k * w for k, w in zip(gamma_key, gamma_weights)) % 65536
    print(f"Computed key checksum: {computed} (0x{computed:04x})")
    assert computed == gamma_target, f"Checksum mismatch: {computed} vs {gamma_target}"

    # Compute collision
    gamma_exploit_bytes = compute_gamma_collision(gamma_key, gamma_weights)
    gamma_exploit = bytes(gamma_exploit_bytes).hex()
    print(f"Gamma collision: {[hex(b) for b in gamma_exploit_bytes]}")
    print(f"Gamma exploit token: {gamma_exploit}")
    assert gamma_exploit != gamma_legit, "Collision is same as key!"

    # Verify collision checksum
    coll_sum = sum(b * w for b, w in zip(gamma_exploit_bytes, gamma_weights)) % 65536
    assert coll_sum == gamma_target, f"Collision checksum wrong: {coll_sum} vs {gamma_target}"

    out = run_vm("/app/auth_gamma.bin", gamma_exploit)
    assert "AUTHENTICATED" in out, f"Gamma exploit failed: {out}"
    print("Gamma exploit verified.")

    # ===== Write Audit Report =====
    audit = {
        "alpha": {
            "vulnerability_class": "hidden-backdoor",
            "cwe": "CWE-912",
            "severity": "critical",
            "exploit_token": alpha_exploit,
            "root_cause": (
                "Hidden authentication bypass triggered by magic prefix bytes "
                "that unconditionally skips all key validation via a direct jump "
                "to the authenticated code path"
            ),
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N",
            "cvss_score": 9.1,
        },
        "beta": {
            "vulnerability_class": "weak-prng-keystream",
            "cwe": "CWE-330",
            "severity": "high",
            "exploit_token": beta_exploit,
            "root_cause": (
                "Authentication keystream derived from a deterministic 8-bit LCG "
                "PRNG with a hardcoded seed, making the entire keystream "
                "predictable to anyone who extracts the firmware constants"
            ),
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N",
            "cvss_score": 9.1,
        },
        "gamma": {
            "vulnerability_class": "weak-hash-comparison",
            "cwe": "CWE-328",
            "severity": "high",
            "exploit_token": gamma_exploit,
            "root_cause": (
                "Authentication uses a weighted linear checksum comparison instead "
                "of byte-by-byte key verification, allowing trivial hash collisions "
                "via modular arithmetic on the weight coefficients"
            ),
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N",
            "cvss_score": 9.1,
        },
        "risk_ranking": ["alpha", "gamma", "beta"],
        "ranking_justification": (
            "Alpha is ranked most critical because the hidden backdoor (CWE-912) "
            "represents intentional sabotage with a trivial 2-byte prefix bypass, "
            "indicating potential supply chain compromise — this is categorically "
            "different from implementation weaknesses. Gamma ranks second because "
            "its checksum collision vulnerability (CWE-328) allows an unbounded "
            "number of valid authentication tokens computable via simple algebra, "
            "reducing the effective key space from 2^64 to 2^48. Beta ranks last "
            "because while its weak PRNG (CWE-330) makes the key deterministically "
            "derivable, it still produces a single valid token and requires "
            "reverse-engineering the PRNG algorithm and constants — a marginally "
            "higher barrier than computing a linear collision."
        ),
    }

    with open("/app/audit.json", "w") as f:
        json.dump(audit, f, indent=2)
    print("\nAudit report written to /app/audit.json")

    # ===== Create Alpha Binary Patch =====
    # Redirect the backdoor JMA instruction to point to no_bd instead of auth_ok
    patched = bytearray(alpha_data)

    jma_code_offset = backdoor_jma[0]  # offset of JMA opcode in code segment
    # Target bytes are at code_offset + 1 (after the opcode byte), in the file
    # that's 8 (header) + jma_code_offset + 1
    target_file_offset = 8 + jma_code_offset + 1
    patched[target_file_offset] = no_bd_addr & 0xFF
    patched[target_file_offset + 1] = (no_bd_addr >> 8) & 0xFF

    with open("/app/auth_alpha_patched.bin", "wb") as f:
        f.write(patched)
    print(f"Patched alpha firmware: JMA target 0x{backdoor_jma[2]:04x} -> 0x{no_bd_addr:04x}")

    # Verify alpha patch
    out = run_vm("/app/auth_alpha_patched.bin", alpha_legit)
    assert "AUTHENTICATED" in out, f"Alpha patch broke legit auth: {out}"
    print("Alpha patch: legit token AUTHENTICATED (OK)")

    out = run_vm("/app/auth_alpha_patched.bin", alpha_exploit)
    assert "DENIED" in out, f"Alpha patch didn't fix backdoor: {out}"
    print("Alpha patch: exploit token DENIED (OK)")

    # ===== Create Gamma Patched Firmware =====
    # Build new firmware with secure byte-by-byte comparison
    gamma_patched_fw = create_gamma_patch(gamma_key)

    with open("/app/auth_gamma_patched.bin", "wb") as f:
        f.write(gamma_patched_fw)
    print(f"Created gamma patched firmware ({len(gamma_patched_fw)} bytes)")

    # Verify gamma patch
    out = run_vm("/app/auth_gamma_patched.bin", gamma_legit)
    assert "AUTHENTICATED" in out, f"Gamma patch broke legit auth: {out}"
    print("Gamma patch: legit token AUTHENTICATED (OK)")

    out = run_vm("/app/auth_gamma_patched.bin", gamma_exploit)
    assert "DENIED" in out, f"Gamma patch still accepts collision: {out}"
    print("Gamma patch: collision exploit DENIED (OK)")

    out = run_vm("/app/auth_gamma_patched.bin", "0000000000000000")
    assert "DENIED" in out, f"Gamma patch accepts garbage: {out}"
    print("Gamma patch: random token DENIED (OK)")

    print("\nAll tasks completed successfully.")


if __name__ == "__main__":
    main()
