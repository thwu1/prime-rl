#!/usr/bin/env python3

"""Fix all bugs in the RVFI trace validator and implement M-extension support.

RV32I Bugs:
  1 (decoder.py):      B-type immediate sign-extended from 12 bits, should be 13.
  2 (decoder.py):      S-type immediate missing sign extension entirely.
  3 (spec_checker.py): SRA/SRAI use logical shift instead of arithmetic (2 sites).
  4 (spec_checker.py): JALR target doesn't clear LSB per RISC-V spec.
  5 (spec_checker.py): LH zero-extends instead of sign-extending halfword.
  6 (spec_checker.py): SB byte store uses wrong write mask (0x3 vs 0x1).
  7 (spec_checker.py): AUIPC handler raises NotImplementedError.
  8 (consistency.py):  PC continuity check ignores intr flag.

M-extension:
  Implement all 8 RV32M instructions (MUL, MULH, MULHSU, MULHU, DIV, DIVU, REM, REMU).
"""

import sys


def fix_decoder():
    """Fix bugs 1 and 2 in decoder.py."""
    path = '/app/rvfi_validator/decoder.py'
    with open(path, 'r') as f:
        code = f.read()

    # Bug 1: B-type immediate sign-extend from 12 bits -> 13 bits
    old = "result['imm'] = sign_extend(raw_imm, 12)  # B-type immediate"
    new = "result['imm'] = sign_extend(raw_imm, 13)  # B-type immediate"
    assert old in code, "Bug 1 target string not found in decoder.py"
    code = code.replace(old, new)

    # Bug 2: S-type immediate missing sign extension
    old = "result['imm'] = raw_imm  # S-type immediate"
    new = "result['imm'] = sign_extend(raw_imm, 12)  # S-type immediate"
    assert old in code, "Bug 2 target string not found in decoder.py"
    code = code.replace(old, new)

    with open(path, 'w') as f:
        f.write(code)
    print("Fixed decoder.py (bugs 1, 2)")


def fix_spec_checker():
    """Fix bugs 3-7 and implement M-extension in spec_checker.py."""
    path = '/app/rvfi_validator/spec_checker.py'
    with open(path, 'r') as f:
        code = f.read()

    # Bug 3: SRA/SRAI logical shift -> arithmetic shift (appears twice)
    old = 'result = mask32(rs1 >> shamt)  # logical shift right'
    new = 'result = mask32(_to_signed32(rs1) >> shamt)  # arithmetic shift right'
    count = code.count(old)
    assert count == 2, f"Bug 3: expected 2 occurrences, found {count}"
    code = code.replace(old, new)

    # Bug 4: JALR target missing LSB clear
    old = "target = mask32(rs1 + imm)  # jalr target"
    new = "target = mask32(rs1 + imm) & 0xFFFFFFFE  # jalr target (clear LSB)"
    assert old in code, "Bug 4 target string not found"
    code = code.replace(old, new)

    # Bug 5: LH zero-extend -> sign-extend
    old = "result = mem_rdata & 0xFFFF  # lh zero extend"
    new = "result = sign_extend(mem_rdata & 0xFFFF, 16)  # lh sign extend"
    assert old in code, "Bug 5 target string not found"
    code = code.replace(old, new)

    # Bug 6: SB write mask 0x3 -> 0x1
    old = "expected_wmask = 0x3  # sb mask"
    new = "expected_wmask = 0x1  # sb mask"
    assert old in code, "Bug 6 target string not found"
    code = code.replace(old, new)

    # Bug 7: AUIPC not implemented -> implement
    old = '''def _check_auipc(dec, rvfi):
    """Check AUIPC instruction."""
    raise NotImplementedError("AUIPC")'''
    new = '''def _check_auipc(dec, rvfi):
    """Check AUIPC instruction."""
    violations = []
    result = mask32(rvfi['pc_rdata'] + dec['imm'])
    violations.extend(_check_rd(dec, rvfi, result))
    violations.extend(_check_pc_next(rvfi, rvfi['pc_rdata'] + 4))
    return violations'''
    assert old in code, "Bug 7 target string not found"
    code = code.replace(old, new)

    # M-extension: replace stub with dispatch to _check_m_ext
    old = '''    if funct7 == 0x01:
        # M-extension (multiply/divide) — not yet implemented
        return []'''
    new = '''    if funct7 == 0x01:
        # M-extension (multiply/divide)
        return _check_m_ext(dec, rvfi, funct3, rs1, rs2)'''
    assert old in code, "M-extension stub not found"
    code = code.replace(old, new)

    # Insert _check_m_ext function definition before _check_i_type
    m_ext_func = '''
def _check_m_ext(dec, rvfi, funct3, rs1, rs2):
    """Check M-extension multiply/divide instructions.

    Handles MUL(0), MULH(1), MULHSU(2), MULHU(3),
    DIV(4), DIVU(5), REM(6), REMU(7).
    """
    violations = []
    s1 = _to_signed32(rs1)
    s2 = _to_signed32(rs2)

    if funct3 == 0:  # MUL: lower 32 bits of product
        result = mask32(rs1 * rs2)
    elif funct3 == 1:  # MULH: signed x signed, upper 32
        product = s1 * s2
        result = mask32(product >> 32)
    elif funct3 == 2:  # MULHSU: signed x unsigned, upper 32
        product = s1 * rs2  # s1 is signed, rs2 stays unsigned
        result = mask32(product >> 32)
    elif funct3 == 3:  # MULHU: unsigned x unsigned, upper 32
        product = rs1 * rs2
        result = mask32(product >> 32)
    elif funct3 == 4:  # DIV: signed division
        if rs2 == 0:
            result = 0xFFFFFFFF  # div by zero -> -1
        elif s1 == -2147483648 and s2 == -1:
            result = 0x80000000  # overflow -> MIN_INT
        else:
            # Truncate toward zero (not floor division)
            q = int(s1 / s2)
            result = mask32(q)
    elif funct3 == 5:  # DIVU: unsigned division
        if rs2 == 0:
            result = 0xFFFFFFFF
        else:
            result = rs1 // rs2
    elif funct3 == 6:  # REM: signed remainder
        if rs2 == 0:
            result = mask32(rs1)  # return dividend
        elif s1 == -2147483648 and s2 == -1:
            result = 0  # overflow -> 0
        else:
            q = int(s1 / s2)
            result = mask32(s1 - q * s2)
    elif funct3 == 7:  # REMU: unsigned remainder
        if rs2 == 0:
            result = rs1  # return dividend
        else:
            result = rs1 % rs2
    else:
        return []

    violations.extend(_check_rd(dec, rvfi, result))
    violations.extend(_check_pc_next(rvfi, rvfi['pc_rdata'] + 4))
    violations.extend(_check_rs_addrs(dec, rvfi))
    return violations


'''

    marker = 'def _check_i_type(dec, rvfi):'
    assert marker in code, "_check_i_type not found for insertion point"
    code = code.replace(marker, m_ext_func + marker)

    with open(path, 'w') as f:
        f.write(code)
    print("Fixed spec_checker.py (bugs 3-7, M-extension implemented)")


def fix_consistency():
    """Fix bug 8 in consistency.py."""
    path = '/app/rvfi_validator/consistency.py'
    with open(path, 'r') as f:
        code = f.read()

    # Bug 8: PC check doesn't account for interrupts
    old = "if self.shadow_pc_valid and rvfi['pc_rdata'] != self.shadow_pc:"
    new = "if self.shadow_pc_valid and rvfi['pc_rdata'] != self.shadow_pc and not rvfi.get('intr', 0):"
    assert old in code, "Bug 8 target string not found"
    code = code.replace(old, new)

    with open(path, 'w') as f:
        f.write(code)
    print("Fixed consistency.py (bug 8)")


if __name__ == '__main__':
    try:
        fix_decoder()
        fix_spec_checker()
        fix_consistency()
        print("\nAll 8 bugs fixed and M-extension implemented successfully.")
    except AssertionError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
