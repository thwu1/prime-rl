#!/usr/bin/env python3
"""
Intel 8086 Microcode-Level MUL/DIV Simulator

Faithfully reproduces the CORX (core multiply) and CORD (core divide)
microcode routines at the register-transfer level.

"""

import json

MASK8 = 0xFF
MASK16 = 0xFFFF


class MicrocodeState:
    def __init__(self, word_mode=True):
        self.tmpA = 0
        self.tmpB = 0
        self.tmpC = 0
        self.cf = 0
        self.f1 = 0
        self.cnt = 0
        self.word_mode = word_mode
        self.mask = MASK16 if word_mode else MASK8
        self.bits = 16 if word_mode else 8

    def rcr(self, val):
        old_cf = self.cf
        self.cf = val & 1
        val = ((old_cf << (self.bits - 1)) | (val >> 1)) & self.mask
        return val

    def rcl(self, val):
        old_cf = self.cf
        top_bit = (val >> (self.bits - 1)) & 1
        val = ((val << 1) | old_cf) & self.mask
        self.cf = top_bit
        return val

    def neg(self, val):
        result = ((~val) + 1) & self.mask
        self.cf = 0 if val == 0 else 1
        return result

    def com1(self, val):
        return (~val) & self.mask

    def add(self, a, b):
        result = a + b
        self.cf = 1 if result > self.mask else 0
        return result & self.mask

    def subt(self, a, b):
        self.cf = 1 if a < b else 0
        return (a - b) & self.mask

    def maxc(self):
        self.cnt = 15 if self.word_mode else 7

    def sign_bit(self, val):
        return (val >> (self.bits - 1)) & 1


def corx(state, trace=False):
    """CORX - Core Multiply. Entry: tmpC=multiplier, tmpB=multiplicand."""
    trace_data = []
    state.tmpA = 0
    state.cf = 0
    state.tmpC = state.rcr(state.tmpC)
    state.maxc()

    if trace:
        trace_data.append({"tmpA": state.tmpA, "tmpC": state.tmpC})

    while True:
        if state.cf == 1:
            state.tmpA = state.add(state.tmpA, state.tmpB)

        state.tmpA = state.rcr(state.tmpA)
        state.tmpC = state.rcr(state.tmpC)

        if trace:
            trace_data.append({"tmpA": state.tmpA, "tmpC": state.tmpC})

        done = (state.cnt == 0)
        state.cnt = max(0, state.cnt - 1)
        if done:
            break

    return trace_data


def cord(state, trace=False):
    """CORD - Core Divide. Returns trace list or None on success, 'error' on overflow."""
    trace_data = []

    # Overflow check
    state.subt(state.tmpA, state.tmpB)
    state.maxc()

    if state.cf == 0:  # tmpA >= tmpB, overflow
        return "error"

    if trace:
        trace_data.append({"tmpA": state.tmpA, "tmpC": state.tmpC})

    while True:
        # RCL tmpC: shift quotient bit (CF) into bottom
        state.tmpC = state.rcl(state.tmpC)
        # RCL tmpA: shift tmpA left, top bit -> CF
        state.tmpA = state.rcl(state.tmpA)

        if state.cf == 1:
            # Top bit was set -> definitely can subtract
            state.cf = 0  # RCY: reset carry
            state.tmpA = (state.tmpA - state.tmpB) & state.mask
            # CF stays 0 (quotient bit: complemented 0 = actual 1)
        else:
            # Compare: tmpA vs tmpB
            cmp_result = (state.tmpA - state.tmpB) & state.mask
            borrow = 1 if state.tmpA < state.tmpB else 0

            if borrow == 0:
                # tmpA >= tmpB: subtract
                state.tmpA = cmp_result
                state.cf = 0  # quotient bit: complemented 0 = actual 1
            else:
                # tmpA < tmpB: don't subtract
                state.cf = 1  # quotient bit: complemented 1 = actual 0

        if trace:
            trace_data.append({"tmpA": state.tmpA, "tmpC": state.tmpC})

        done = (state.cnt == 0)
        state.cnt = max(0, state.cnt - 1)
        if done:
            break

    # Step 12: two more RCLs on tmpC
    state.tmpC = state.rcl(state.tmpC)  # pick up last quotient bit
    _ = state.rcl(state.tmpC)  # put top bit into CF (for POSTIDIV), discard result

    return trace_data if trace else None


def negate_32bit(state):
    """Negate 32-bit value in tmpA:tmpC."""
    state.tmpC = state.neg(state.tmpC)
    if state.cf == 1:  # tmpC was non-zero
        state.tmpA = state.com1(state.tmpA)
    else:  # tmpC was zero, carry propagates
        state.tmpA = state.neg(state.tmpA)


def preimul(state):
    """Pre-processing for signed multiply (IMUL)."""
    state.f1 = 0
    if state.sign_bit(state.tmpC):
        state.tmpC = state.neg(state.tmpC)
        state.f1 ^= 1
    if state.sign_bit(state.tmpB):
        state.tmpB = state.neg(state.tmpB)
        state.f1 ^= 1


def preidiv(state):
    """Pre-processing for signed divide (IDIV)."""
    state.f1 = 0
    if state.sign_bit(state.tmpA):
        negate_32bit(state)
        state.f1 ^= 1
    if state.sign_bit(state.tmpB):
        state.tmpB = state.neg(state.tmpB)
        state.f1 ^= 1


def postidiv(state, orig_dx):
    """Post-processing for signed divide. tmpC holds COMPLEMENTED quotient."""
    # Check overflow: CF from CORD's final RCL = top bit of complemented quotient
    # CF=0 means top bit of actual quotient is 1 -> too large for signed
    if state.cf == 0:
        return "error"

    # Check sign of original dividend (upper word)
    if state.sign_bit(orig_dx):
        state.tmpA = state.neg(state.tmpA)  # negate remainder

    # Handle quotient
    if state.f1 == 1:
        # Result should be negative: INC converts complemented -> two's complement
        state.tmpC = (state.tmpC + 1) & state.mask
    else:
        # Result should be positive: COM1 converts complemented -> actual
        state.tmpC = state.com1(state.tmpC)

    state.cf = 0
    return None


def mulcof(state):
    if state.tmpA != 0:
        return 1, 1
    return 0, 0


def imulcof(state):
    top_bit = state.sign_bit(state.tmpC)
    expected_high = state.mask if top_bit else 0
    if state.tmpA == expected_high:
        return 0, 0
    return 1, 1


def mul_word(ax, operand):
    state = MicrocodeState(word_mode=True)
    state.tmpC = ax & MASK16
    state.tmpB = operand & MASK16
    corx(state)
    cf, of = mulcof(state)
    return {"ax": state.tmpC, "dx": state.tmpA, "cf": cf, "of": of}


def mul_byte(al, operand):
    state = MicrocodeState(word_mode=False)
    state.tmpC = al & MASK8
    state.tmpB = operand & MASK8
    corx(state)
    cf, of = mulcof(state)
    return {"al": state.tmpC, "ah": state.tmpA, "cf": cf, "of": of}


def imul_word(ax, operand):
    state = MicrocodeState(word_mode=True)
    state.tmpC = ax & MASK16
    state.tmpB = operand & MASK16
    preimul(state)
    corx(state)
    if state.f1 == 1:
        negate_32bit(state)
        state.f1 ^= 1
    cf, of = imulcof(state)
    return {"ax": state.tmpC, "dx": state.tmpA, "cf": cf, "of": of}


def div_word(dx, ax, divisor):
    state = MicrocodeState(word_mode=True)
    state.tmpA = dx & MASK16
    state.tmpC = ax & MASK16
    state.tmpB = divisor & MASK16
    result = cord(state)
    if result == "error":
        return {"error": True}
    state.tmpC = state.com1(state.tmpC)
    return {"ax": state.tmpC, "dx": state.tmpA}


def div_byte(ax_val, divisor):
    state = MicrocodeState(word_mode=False)
    state.tmpA = (ax_val >> 8) & MASK8
    state.tmpC = ax_val & MASK8
    state.tmpB = divisor & MASK8
    result = cord(state)
    if result == "error":
        return {"error": True}
    state.tmpC = state.com1(state.tmpC)
    return {"al": state.tmpC, "ah": state.tmpA}


def idiv_word(dx, ax, divisor):
    orig_dx = dx & MASK16
    state = MicrocodeState(word_mode=True)
    state.tmpA = dx & MASK16
    state.tmpC = ax & MASK16
    state.tmpB = divisor & MASK16
    preidiv(state)
    result = cord(state)
    if result == "error":
        return {"error": True}
    err = postidiv(state, orig_dx)
    if err == "error":
        return {"error": True}
    return {"ax": state.tmpC, "dx": state.tmpA}


def mul_word_trace(ax, operand):
    state = MicrocodeState(word_mode=True)
    state.tmpC = ax & MASK16
    state.tmpB = operand & MASK16
    return corx(state, trace=True)


def div_word_trace(dx, ax, divisor):
    state = MicrocodeState(word_mode=True)
    state.tmpA = dx & MASK16
    state.tmpC = ax & MASK16
    state.tmpB = divisor & MASK16
    result = cord(state, trace=True)
    if result == "error":
        return []
    return result


def get_all_results():
    """Compute all simulator results and return as dict."""
    results = {}

    results["mul_word"] = [
        mul_word(0xFFFF, 0xF00F),
        mul_word(0x0003, 0x0005),
        mul_word(0x8000, 0x0002),
    ]

    results["mul_byte"] = [
        mul_byte(0xFF, 0x55),
        mul_byte(0x03, 0x07),
    ]

    results["imul_word"] = [
        imul_word(0xFFF9, 0x0007),
        imul_word(0x0003, 0x0005),
        imul_word(0xFFFC, 0xFFFE),
    ]

    results["div_word"] = [
        div_word(0x0F00, 0xFF00, 0x0FFC),
        div_word(0x0000, 0x0043, 0x000A),
        div_word(0x0000, 0x0064, 0x000A),
    ]

    results["div_byte"] = [
        div_byte(0x2345, 0x34),
        div_byte(0x0064, 0x0A),
    ]

    results["idiv_word"] = [
        idiv_word(0xFFFF, 0xFFE5, 0x0007),
        idiv_word(0xFFFF, 0xFFE5, 0xFFF9),
        idiv_word(0x0000, 0x001B, 0xFFF9),
    ]

    results["div_overflow"] = [
        div_word(0x0001, 0x0000, 0x0001),
        div_word(0x0000, 0x0005, 0x0000),
    ]

    results["mul_trace"] = mul_word_trace(0xFFFF, 0xF00F)
    results["div_trace"] = div_word_trace(0x0F00, 0xFF00, 0x0FFC)

    return results


def main():
    results = get_all_results()
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
