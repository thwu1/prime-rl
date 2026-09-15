"""
Tests for the Intel 8086 microcode ROM decoder, division simulator,
and NASM-based hardware validation.

"""

import json
import os
import re
import sys

import pytest

sys.path.insert(0, "/app")
from simulator import DivisionOverflow, execute_div


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _to_signed(val, bits):
    if val >= (1 << (bits - 1)):
        return val - (1 << bits)
    return val


def _to_unsigned(val, bits):
    return val & ((1 << bits) - 1)


def _ref_unsigned_word(dx, ax, divisor):
    dividend = (dx << 16) | ax
    if divisor == 0 or dx >= divisor:
        return None
    q = dividend // divisor
    r = dividend % divisor
    if q > 0xFFFF:
        return None
    return (q, r)


def _ref_unsigned_byte(ax, divisor):
    if divisor == 0 or (ax >> 8) >= divisor:
        return None
    q = ax // divisor
    r = ax % divisor
    if q > 0xFF:
        return None
    return (q, r)


def _reference_div(dividend_hi, dividend_lo, divisor, signed, byte_mode):
    """Full reference implementation for expected division results."""
    bits = 8 if byte_mode else 16
    mask = (1 << bits) - 1

    if byte_mode:
        tmpA = (dividend_lo >> 8) & 0xFF
        tmpC = dividend_lo & 0xFF
        tmpB = divisor & 0xFF
    else:
        tmpA = dividend_hi & 0xFFFF
        tmpC = dividend_lo & 0xFFFF
        tmpB = divisor & 0xFFFF

    original_tmpA = tmpA
    f1 = 0

    if signed:
        if (tmpA >> (bits - 1)) & 1:
            old_tmpC = tmpC
            tmpC = (-tmpC) & mask
            if old_tmpC != 0:
                tmpA = (~tmpA) & mask
            else:
                tmpA = (-tmpA) & mask
            f1 ^= 1
        if (tmpB >> (bits - 1)) & 1:
            tmpB = (-tmpB) & mask
            f1 ^= 1

    if tmpB == 0 or tmpA >= tmpB:
        return None

    carry = 1
    for _ in range(bits):
        new_carry = (tmpC >> (bits - 1)) & 1
        tmpC = ((tmpC << 1) | carry) & mask
        carry = new_carry
        new_carry = (tmpA >> (bits - 1)) & 1
        tmpA = ((tmpA << 1) | carry) & mask
        carry = new_carry
        if carry:
            tmpA = (tmpA - tmpB) & mask
            carry = 0
        else:
            if tmpA >= tmpB:
                tmpA = tmpA - tmpB
                carry = 0
            else:
                carry = 1

    new_carry = (tmpC >> (bits - 1)) & 1
    tmpC = ((tmpC << 1) | carry) & mask

    quotient = (~tmpC) & mask
    remainder = tmpA

    if signed:
        if (quotient >> (bits - 1)) & 1:
            return None
        if (original_tmpA >> (bits - 1)) & 1:
            remainder = (-remainder) & mask
        if f1:
            quotient = (-quotient) & mask

    return (quotient, remainder)


def _extract_routine(text, routine_name):
    """Extract instruction lines for a routine from disassembly text."""
    lines = text.split('\n')
    in_routine = False
    instructions = {}
    for line in lines:
        upper = line.upper().strip()
        # Detect routine headers
        if routine_name.upper() in upper and ('===' in line or '---' in line or
                (routine_name.upper() + ' ' in upper and '(' in upper) or
                upper.startswith(routine_name.upper() + ':')):
            in_routine = True
            continue
        if in_routine:
            # Check if we hit a new routine header
            for other in ['CORD', 'PREIDIV', 'POSTIDIV', 'DIV_WORD', 'DIV_BYTE']:
                if other != routine_name.upper() and other in upper and (
                        '===' in line or '---' in line or
                        (other + ' ' in upper and '(' in upper) or
                        upper.startswith(other + ':')):
                    in_routine = False
                    break
            if not in_routine:
                continue
            m = re.match(r'\s*(\d+)\s*[:.]\s*(.*)', line)
            if m:
                instructions[int(m.group(1))] = m.group(2)
    return instructions


# ═══════════════════════════════════════════════════════════════════
# 1. ROM Disassembly Tests
# ═══════════════════════════════════════════════════════════════════

class TestDisassemblyExists:
    def test_file_exists(self):
        assert os.path.exists('/app/disassembly.txt'), "disassembly.txt not found"

    def test_file_nonempty(self):
        size = os.path.getsize('/app/disassembly.txt')
        assert size > 100, f"disassembly.txt too small ({size} bytes)"


class TestDisassemblyRoutines:
    @pytest.fixture(scope='class')
    def text(self):
        with open('/app/disassembly.txt') as f:
            return f.read()

    def test_has_cord(self, text):
        assert 'CORD' in text.upper()

    def test_has_preidiv(self, text):
        assert 'PREIDIV' in text.upper()

    def test_has_postidiv(self, text):
        assert 'POSTIDIV' in text.upper()

    def test_has_div_word(self, text):
        assert 'DIV_WORD' in text.upper() or 'DIVWORD' in text.upper()

    def test_has_div_byte(self, text):
        assert 'DIV_BYTE' in text.upper() or 'DIVBYTE' in text.upper()


class TestDisassemblyCORD:
    @pytest.fixture(scope='class')
    def inst(self):
        with open('/app/disassembly.txt') as f:
            text = f.read()
        return _extract_routine(text, 'CORD')

    def test_instruction_count(self, inst):
        assert len(inst) == 16, f"CORD should have 16 instructions, got {len(inst)}"

    def test_line0_subt_tmpa(self, inst):
        line = inst.get(0, '')
        assert 'SUBT' in line.upper(), f"CORD[0] should contain SUBT: {line}"
        assert 'TMPA' in line.upper() or 'tmpA' in line, f"CORD[0] should reference tmpA: {line}"

    def test_line3_rcl_tmpc(self, inst):
        line = inst.get(3, '')
        assert 'RCL' in line.upper(), f"CORD[3] should contain RCL: {line}"
        assert 'TMPC' in line.upper() or 'tmpC' in line, f"CORD[3] should reference tmpC: {line}"

    def test_line4_sigma_to_tmpc(self, inst):
        line = inst.get(4, '')
        upper = line.upper()
        assert 'SIGMA' in upper or 'Σ' in line, f"CORD[4] should have SIGMA source: {line}"
        assert 'TMPC' in upper or 'tmpC' in line, f"CORD[4] should have tmpC destination: {line}"

    def test_line6_jmp_cy_13(self, inst):
        line = inst.get(6, '')
        upper = line.upper()
        assert 'CY' in upper, f"CORD[6] should have CY condition: {line}"
        assert '13' in line, f"CORD[6] should jump to 13: {line}"

    def test_line12_return(self, inst):
        line = inst.get(12, '')
        upper = line.upper()
        assert 'RTN' in upper or 'RETURN' in upper or 'RET' in upper, \
            f"CORD[12] should be a return: {line}"

    def test_line13_rcy(self, inst):
        line = inst.get(13, '')
        assert 'RCY' in line.upper(), f"CORD[13] should contain RCY: {line}"

    def test_line15_jmp_10(self, inst):
        line = inst.get(15, '')
        assert '10' in line, f"CORD[15] should jump to 10: {line}"
        assert 'UNC' in line.upper(), f"CORD[15] should be unconditional: {line}"


class TestDisassemblyPREIDIV:
    @pytest.fixture(scope='class')
    def inst(self):
        with open('/app/disassembly.txt') as f:
            text = f.read()
        return _extract_routine(text, 'PREIDIV')

    def test_instruction_count(self, inst):
        assert len(inst) == 12, f"PREIDIV should have 12 instructions, got {len(inst)}"

    def test_line2_neg_tmpc(self, inst):
        line = inst.get(2, '')
        assert 'NEG' in line.upper(), f"PREIDIV[2] should contain NEG: {line}"
        assert 'TMPC' in line.upper() or 'tmpC' in line, f"PREIDIV[2] should reference tmpC: {line}"

    def test_line3_com1_tmpa(self, inst):
        line = inst.get(3, '')
        assert 'COM1' in line.upper(), f"PREIDIV[3] should contain COM1: {line}"

    def test_line6_cf1(self, inst):
        line = inst.get(6, '')
        assert 'CF1' in line.upper(), f"PREIDIV[6] should contain CF1: {line}"

    def test_line7_rcl_tmpb(self, inst):
        line = inst.get(7, '')
        assert 'RCL' in line.upper(), f"PREIDIV[7] should contain RCL: {line}"
        assert 'TMPB' in line.upper() or 'tmpB' in line, f"PREIDIV[7] should reference tmpB: {line}"


class TestDisassemblyPOSTIDIV:
    @pytest.fixture(scope='class')
    def inst(self):
        with open('/app/disassembly.txt') as f:
            text = f.read()
        return _extract_routine(text, 'POSTIDIV')

    def test_instruction_count(self, inst):
        assert len(inst) == 9, f"POSTIDIV should have 9 instructions, got {len(inst)}"

    def test_line0_ncy_int0(self, inst):
        line = inst.get(0, '')
        upper = line.upper()
        assert 'NCY' in upper, f"POSTIDIV[0] should have NCY condition: {line}"
        assert 'INT0' in upper or 'INT' in upper, f"POSTIDIV[0] should target INT0: {line}"

    def test_line5_inc_tmpc(self, inst):
        line = inst.get(5, '')
        assert 'INC' in line.upper(), f"POSTIDIV[5] should contain INC: {line}"
        assert 'TMPC' in line.upper() or 'tmpC' in line, f"POSTIDIV[5] should reference tmpC: {line}"

    def test_line7_com1_tmpc(self, inst):
        line = inst.get(7, '')
        assert 'COM1' in line.upper(), f"POSTIDIV[7] should contain COM1: {line}"


class TestDisassemblyDIV_WORD:
    @pytest.fixture(scope='class')
    def inst(self):
        with open('/app/disassembly.txt') as f:
            text = f.read()
        return _extract_routine(text, 'DIV_WORD')

    def test_instruction_count(self, inst):
        assert len(inst) == 8, f"DIV_WORD should have 8 instructions, got {len(inst)}"

    def test_line0_dx_to_tmpa(self, inst):
        line = inst.get(0, '')
        upper = line.upper()
        assert 'DX' in upper, f"DIV_WORD[0] should have DX: {line}"
        assert 'TMPA' in upper or 'tmpA' in line, f"DIV_WORD[0] should target tmpA: {line}"

    def test_line6_sigma_to_ax(self, inst):
        line = inst.get(6, '')
        upper = line.upper()
        assert 'SIGMA' in upper or 'Σ' in line, f"DIV_WORD[6] should have SIGMA source: {line}"
        assert 'AX' in upper, f"DIV_WORD[6] should target AX: {line}"


class TestDisassemblyDIV_BYTE:
    @pytest.fixture(scope='class')
    def inst(self):
        with open('/app/disassembly.txt') as f:
            text = f.read()
        return _extract_routine(text, 'DIV_BYTE')

    def test_instruction_count(self, inst):
        assert len(inst) == 8, f"DIV_BYTE should have 8 instructions, got {len(inst)}"

    def test_line0_ah_to_tmpa(self, inst):
        line = inst.get(0, '')
        upper = line.upper()
        assert 'AH' in upper, f"DIV_BYTE[0] should have AH: {line}"
        assert 'TMPA' in upper or 'tmpA' in line, f"DIV_BYTE[0] should target tmpA: {line}"

    def test_line7_tmpa_to_ah(self, inst):
        line = inst.get(7, '')
        upper = line.upper()
        assert 'AH' in upper, f"DIV_BYTE[7] should reference AH: {line}"
        assert 'TMPA' in upper or 'tmpA' in line, f"DIV_BYTE[7] should have tmpA source: {line}"


# ═══════════════════════════════════════════════════════════════════
# 2. Division Simulator Tests
# ═══════════════════════════════════════════════════════════════════

class TestUnsignedWordDiv:
    def test_simple(self):
        assert execute_div(0x0000, 0x000A, 0x0003) == (3, 1)

    def test_exact(self):
        assert execute_div(0x0000, 0x0064, 0x000A) == (10, 0)

    def test_blog_example(self):
        assert execute_div(0x0F00, 0xFF00, 0x0FFC) == (0xF04C, 0x0030)

    def test_dx_nonzero(self):
        assert execute_div(0x0001, 0x0000, 0x0100) == (256, 0)

    def test_zero_dividend(self):
        assert execute_div(0x0000, 0x0000, 0x0001) == (0, 0)

    def test_max_quotient(self):
        assert execute_div(0x0000, 0xFFFF, 0x0001) == (0xFFFF, 0)

    def test_equal_operands(self):
        assert execute_div(0x0000, 0xFFFF, 0xFFFF) == (1, 0)

    def test_large_remainder(self):
        assert execute_div(0x0000, 0x000B, 0x0003) == (3, 2)

    def test_complex(self):
        ref = _ref_unsigned_word(0x1234, 0x5678, 0x9ABC)
        assert ref is not None
        assert execute_div(0x1234, 0x5678, 0x9ABC) == ref

    def test_dx_just_below_divisor(self):
        ref = _ref_unsigned_word(0x0009, 0xABCD, 0x000A)
        assert ref is not None
        assert execute_div(0x0009, 0xABCD, 0x000A) == ref

    def test_large_divisor(self):
        ref = _ref_unsigned_word(0x7FFF, 0x0000, 0x8000)
        assert ref is not None
        assert execute_div(0x7FFF, 0x0000, 0x8000) == ref

    def test_power_of_two_divisor(self):
        ref = _ref_unsigned_word(0x0000, 0x8000, 0x0100)
        assert ref is not None
        assert execute_div(0x0000, 0x8000, 0x0100) == ref


class TestUnsignedWordDivOverflow:
    def test_divide_by_zero(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0x0000, 0x0001, 0x0000)

    def test_quotient_overflow(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0x0001, 0x0000, 0x0001)

    def test_large_overflow(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0xFFFF, 0x0000, 0x0001)

    def test_dx_equals_divisor(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0x1234, 0x5678, 0x1234)

    def test_zero_dividend_zero_divisor(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0x0000, 0x0000, 0x0000)


class TestUnsignedByteDiv:
    def test_simple(self):
        assert execute_div(0, 0x0064, 0x0A, byte_mode=True) == (10, 0)

    def test_blog_byte_example(self):
        assert execute_div(0, 0x2345, 0x34, byte_mode=True) == (0xAD, 0x21)

    def test_max_valid(self):
        assert execute_div(0, 0x00FF, 0x01, byte_mode=True) == (0xFF, 0)

    def test_remainder(self):
        assert execute_div(0, 0x000B, 0x03, byte_mode=True) == (3, 2)

    def test_large_ah(self):
        ref = _ref_unsigned_byte(0x09FF, 0x0A)
        assert ref is not None
        assert execute_div(0, 0x09FF, 0x0A, byte_mode=True) == ref

    def test_exact_byte(self):
        assert execute_div(0, 0x0040, 0x08, byte_mode=True) == (8, 0)


class TestUnsignedByteDivOverflow:
    def test_divide_by_zero(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0, 0x0001, 0x00, byte_mode=True)

    def test_quotient_overflow(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0, 0x0100, 0x01, byte_mode=True)

    def test_ah_ge_divisor(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0, 0x2300, 0x01, byte_mode=True)


class TestSignedWordDiv:
    def test_positive_positive(self):
        assert execute_div(0x0000, 0x001B, 0x0007, signed=True) == (3, 6)

    def test_negative_positive(self):
        assert execute_div(0xFFFF, 0xFFE5, 0x0007, signed=True) == (0xFFFD, 0xFFFA)

    def test_positive_negative(self):
        assert execute_div(0x0000, 0x001B, 0xFFF9, signed=True) == (0xFFFD, 6)

    def test_negative_negative(self):
        assert execute_div(0xFFFF, 0xFFE5, 0xFFF9, signed=True) == (3, 0xFFFA)

    def test_max_positive_quotient(self):
        assert execute_div(0x0000, 0x7FFF, 0x0001, signed=True) == (0x7FFF, 0)

    def test_max_negative_quotient_valid(self):
        assert execute_div(0xFFFF, 0x8001, 0x0001, signed=True) == (0x8001, 0)

    def test_negative_div_negative_large(self):
        val = -131068 & 0xFFFFFFFF
        dx = (val >> 16) & 0xFFFF
        ax = val & 0xFFFF
        assert execute_div(dx, ax, 0xFFFC, signed=True) == (0x7FFF, 0)

    def test_one_div_minus_one(self):
        assert execute_div(0x0000, 0x0001, 0xFFFF, signed=True) == (0xFFFF, 0)

    def test_minus_one_div_one(self):
        assert execute_div(0xFFFF, 0xFFFF, 0x0001, signed=True) == (0xFFFF, 0)

    def test_zero_dividend_signed(self):
        assert execute_div(0x0000, 0x0000, 0x0005, signed=True) == (0, 0)

    def test_remainder_sign_matches_dividend(self):
        val = -10 & 0xFFFFFFFF
        dx = (val >> 16) & 0xFFFF
        ax = val & 0xFFFF
        q, r = execute_div(dx, ax, 0x0003, signed=True)
        assert q == _to_unsigned(-3, 16)
        assert r == _to_unsigned(-1, 16)

    def test_remainder_sign_positive_dividend(self):
        q, r = execute_div(0x0000, 0x000A, 0xFFFD, signed=True)
        assert q == _to_unsigned(-3, 16)
        assert r == 1


class TestSignedByteDiv:
    def test_positive(self):
        assert execute_div(0, 0x001B, 0x07, signed=True, byte_mode=True) == (3, 6)

    def test_negative_dividend(self):
        q, r = execute_div(0, 0xFFE5, 0x07, signed=True, byte_mode=True)
        assert q == _to_unsigned(-3, 8)
        assert r == _to_unsigned(-6, 8)

    def test_negative_divisor(self):
        q, r = execute_div(0, 0x001B, 0xF9, signed=True, byte_mode=True)
        assert q == _to_unsigned(-3, 8)
        assert r == 6

    def test_both_negative(self):
        q, r = execute_div(0, 0xFFE5, 0xF9, signed=True, byte_mode=True)
        assert q == 3
        assert r == _to_unsigned(-6, 8)

    def test_max_positive_byte_quotient(self):
        assert execute_div(0, 0x007F, 0x01, signed=True, byte_mode=True) == (0x7F, 0)

    def test_max_negative_byte_quotient_valid(self):
        assert execute_div(0, 0xFF81, 0x01, signed=True, byte_mode=True) == (0x81, 0)


class TestSignedOverflowQuirk:
    def test_word_minus_32768_overflow(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0xFFFF, 0x8000, 0x0001, signed=True)

    def test_word_32768_positive_overflow(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0x0000, 0x8000, 0x0001, signed=True)

    def test_byte_minus_128_overflow(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0, 0xFF80, 0x01, signed=True, byte_mode=True)

    def test_byte_128_positive_overflow(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0, 0x0080, 0x01, signed=True, byte_mode=True)

    def test_word_minus_131072_div_4_overflow(self):
        val = -131072 & 0xFFFFFFFF
        dx = (val >> 16) & 0xFFFF
        ax = val & 0xFFFF
        with pytest.raises(DivisionOverflow):
            execute_div(dx, ax, 0x0004, signed=True)


class TestSignedDivOverflow:
    def test_divide_by_zero_signed(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0x0000, 0x0001, 0x0000, signed=True)

    def test_large_positive_dividend(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0x0001, 0x0000, 0x0001, signed=True)

    def test_byte_divide_by_zero_signed(self):
        with pytest.raises(DivisionOverflow):
            execute_div(0, 0x0001, 0x00, signed=True, byte_mode=True)


# ═══════════════════════════════════════════════════════════════════
# Parametrized stress tests
# ═══════════════════════════════════════════════════════════════════

_STRESS_UNSIGNED_WORD = [
    (0x0000, 0x4321, 0x0011),
    (0x0000, 0xBEEF, 0x00FF),
    (0x00AB, 0xCDEF, 0x0ABC),
    (0x0FFF, 0xFFFF, 0x1000),
    (0x0000, 0x0001, 0xFFFF),
    (0x7FFE, 0xFFFF, 0x7FFF),
    (0x0000, 0xFFFE, 0x0002),
    (0x0003, 0x0000, 0x0004),
    (0x0000, 0x8000, 0x0003),
    (0x1000, 0x0000, 0x2000),
]

_STRESS_UNSIGNED_BYTE = [
    (0x0064, 0x0A), (0x00FF, 0x10), (0x0345, 0x34), (0x0A00, 0x0B),
    (0x007F, 0x02), (0x01FE, 0x02), (0x0999, 0x0A), (0x0050, 0x07),
]

_STRESS_SIGNED_WORD = [
    (0xFFFF, 0xFFF6, 0x0003),
    (0x0000, 0x000A, 0xFFFD),
    (0xFFFF, 0xFFF6, 0xFFFD),
    (0xFFFF, 0x8001, 0x0001),
    (0x0000, 0x7FFF, 0xFFFF),
    (0xFFFF, 0xFFFF, 0xFFFF),
    (0xFFFF, 0xFFFE, 0x0002),
    (0x0000, 0x0064, 0xFFF6),
]

_STRESS_SIGNED_BYTE = [
    (0xFFF6, 0x03), (0x000A, 0xFD), (0xFFF6, 0xFD),
    (0xFF81, 0x01), (0x007F, 0xFF), (0x0064, 0xF6),
]


class TestStressUnsignedWord:
    @pytest.mark.parametrize("dx,ax,div", _STRESS_UNSIGNED_WORD)
    def test_stress(self, dx, ax, div):
        ref = _reference_div(dx, ax, div, False, False)
        if ref is None:
            with pytest.raises(DivisionOverflow):
                execute_div(dx, ax, div)
        else:
            assert execute_div(dx, ax, div) == ref


class TestStressUnsignedByte:
    @pytest.mark.parametrize("ax,div", _STRESS_UNSIGNED_BYTE)
    def test_stress(self, ax, div):
        ref = _reference_div(0, ax, div, False, True)
        if ref is None:
            with pytest.raises(DivisionOverflow):
                execute_div(0, ax, div, byte_mode=True)
        else:
            assert execute_div(0, ax, div, byte_mode=True) == ref


class TestStressSignedWord:
    @pytest.mark.parametrize("dx,ax,div", _STRESS_SIGNED_WORD)
    def test_stress(self, dx, ax, div):
        ref = _reference_div(dx, ax, div, True, False)
        if ref is None:
            with pytest.raises(DivisionOverflow):
                execute_div(dx, ax, div, signed=True)
        else:
            assert execute_div(dx, ax, div, signed=True) == ref


class TestStressSignedByte:
    @pytest.mark.parametrize("ax,div", _STRESS_SIGNED_BYTE)
    def test_stress(self, ax, div):
        ref = _reference_div(0, ax, div, True, True)
        if ref is None:
            with pytest.raises(DivisionOverflow):
                execute_div(0, ax, div, signed=True, byte_mode=True)
        else:
            assert execute_div(0, ax, div, signed=True, byte_mode=True) == ref


# ═══════════════════════════════════════════════════════════════════
# 3. NASM Ground Truth Validation Tests
# ═══════════════════════════════════════════════════════════════════

class TestNASMEvidence:
    def test_asm_source_exists(self):
        assert os.path.exists('/app/test_div.asm'), \
            "NASM source file /app/test_div.asm not found"

    def test_asm_source_has_div_instructions(self):
        with open('/app/test_div.asm') as f:
            content = f.read()
        # Filter out comment-only lines
        code_lines = [l.strip() for l in content.split('\n')
                      if l.strip() and not l.strip().startswith(';')]
        has_div = any(re.search(r'\b(i?div)\b', l, re.IGNORECASE) for l in code_lines)
        assert has_div, "NASM source must contain div or idiv instructions"

    def test_assembled_binary_exists(self):
        has_obj = os.path.exists('/app/test_div.o')
        has_bin = os.path.exists('/app/test_div')
        assert has_obj or has_bin, \
            "Assembled object (.o) or linked binary must exist"

    def test_object_is_elf(self):
        """Verify the assembled object is a real ELF file."""
        for path in ['/app/test_div.o', '/app/test_div']:
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    magic = f.read(4)
                assert magic == b'\x7fELF', \
                    f"{path} does not appear to be a valid ELF file"
                return
        pytest.skip("No assembled binary found")


class TestGroundTruthJSON:
    @pytest.fixture(scope='class')
    def gt(self):
        assert os.path.exists('/app/ground_truth.json'), \
            "ground_truth.json not found"
        with open('/app/ground_truth.json') as f:
            return json.load(f)

    def test_has_test_vectors(self, gt):
        assert 'test_vectors' in gt
        assert len(gt['test_vectors']) >= 5, \
            f"Expected at least 5 test vectors, got {len(gt['test_vectors'])}"

    def _find_vector(self, gt, dx, ax, divisor, signed, mode):
        for v in gt['test_vectors']:
            if (v.get('dx', 0) == dx and v.get('ax') == ax and
                    v.get('divisor') == divisor and
                    v.get('signed', False) == signed and
                    v.get('mode') == mode):
                return v
        return None

    def test_unsigned_word_simple(self, gt):
        v = self._find_vector(gt, 0x0000, 0x000A, 0x0003, False, 'word')
        assert v is not None, "Missing unsigned word vector (10/3)"
        assert v['quotient'] == 3
        assert v['remainder'] == 1

    def test_unsigned_word_blog(self, gt):
        v = self._find_vector(gt, 0x0F00, 0xFF00, 0x0FFC, False, 'word')
        assert v is not None, "Missing unsigned word vector (0x0F00FF00/0x0FFC)"
        assert v['quotient'] == 0xF04C
        assert v['remainder'] == 0x0030

    def test_unsigned_byte(self, gt):
        v = self._find_vector(gt, 0, 0x2345, 0x34, False, 'byte')
        assert v is not None, "Missing unsigned byte vector (0x2345/0x34)"
        assert v['quotient'] == 0xAD
        assert v['remainder'] == 0x21

    def test_signed_word_neg_div_pos(self, gt):
        v = self._find_vector(gt, 0xFFFF, 0xFFE5, 0x0007, True, 'word')
        assert v is not None, "Missing signed word vector (-27/7)"
        assert v['quotient'] == 0xFFFD
        assert v['remainder'] == 0xFFFA

    def test_signed_word_pos_div_neg(self, gt):
        v = self._find_vector(gt, 0x0000, 0x001B, 0xFFF9, True, 'word')
        assert v is not None, "Missing signed word vector (27/-7)"
        assert v['quotient'] == 0xFFFD
        assert v['remainder'] == 0x0006
