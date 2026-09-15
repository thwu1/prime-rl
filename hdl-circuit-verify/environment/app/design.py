"""
4-bit ALU design using the miniHDL framework.

Opcodes (3-bit):
  000  ADD   a + b
  001  SUB   a - b
  010  AND   a & b
  011  OR    a | b
  100  XOR   a ^ b
  101  NOT   ~a
  110  SHL   a << 1
  111  SHR   a >> 1

All operands and results are unsigned 4-bit integers.
"""


from hdl import Wire, Bus, mux, const


def half_adder(a, b):
    s = a ^ b
    c = a & b
    return s, c


def full_adder(a, b, cin):
    s1 = a ^ b
    s  = s1 ^ cin
    c1 = a & b
    c2 = a & cin
    c  = c1 | c2
    return s, c


def ripple_adder(a, b, cin_wire):
    n = len(a)
    sums = []
    carry = cin_wire
    for i in range(n):
        s, carry = full_adder(a[i], b[i], carry)
        sums.append(s)
    return Bus(sums), carry


def subtractor(a, b):
    not_b = ~b
    result, _ = ripple_adder(a, not_b, const(0))
    return result


def shift_left(a):
    return Bus([const(0)] + [a[i] for i in range(len(a) - 1)])


def shift_right(a):
    n = len(a)
    return Bus([a[(i + 1) % n] for i in range(n)])


def build_alu(opcode, a, b):
    res_add, _ = ripple_adder(a, b, const(0))
    res_sub    = subtractor(a, b)
    res_and    = a & b
    res_or     = a | b
    res_xor    = a ^ b
    res_not    = ~a
    res_shl    = shift_left(a)
    res_shr    = shift_right(a)

    m0 = mux(opcode[0], res_sub, res_add)
    m1 = mux(opcode[0], res_or,  res_and)
    m2 = mux(opcode[0], res_xor, res_not)
    m3 = mux(opcode[0], res_shr, res_shl)

    lo = mux(opcode[1], m1, m0)
    hi = mux(opcode[1], m3, m2)

    return mux(opcode[2], hi, lo)
