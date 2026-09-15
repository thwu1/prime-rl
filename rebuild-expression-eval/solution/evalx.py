#!/usr/bin/env python3
"""
Functionally equivalent reimplementation of /app/evalx.
"""
import sys
import struct

MASK32 = 0xFFFFFFFF
MASK64 = 0xFFFFFFFFFFFFFFFF
HASH_C = 0x9E3779B1
FEISTEL_KEYS = [0xA3B1C6D7, 0x1F2E3D4C, 0x5A6B7C8D, 0xE9F0A1B2]

# ── Tokenizer ──

T_NUM, T_ID, T_PLUS, T_MINUS, T_MUL, T_DIV, T_MOD = range(7)
T_AND, T_OR, T_XOR, T_NOT, T_SHL, T_SHR = range(7, 13)
T_POW, T_HASH, T_ROT, T_BYTE = range(13, 17)
T_LP, T_RP, T_COMMA, T_END, T_ERR = range(17, 22)


class Lexer:
    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.tok = None
        self.tok_num = 0
        self.tok_id = ""
        self.advance()

    def advance(self):
        while self.pos < len(self.text) and self.text[self.pos] in " \t":
            self.pos += 1
        if self.pos >= len(self.text):
            self.tok = T_END
            return
        c = self.text[self.pos]
        if (c == '0' and self.pos + 2 < len(self.text)
                and self.text[self.pos + 1] in 'xX'
                and self.text[self.pos + 2] in '0123456789abcdefABCDEF'):
            end = self.pos + 2
            while end < len(self.text) and self.text[end] in '0123456789abcdefABCDEF':
                end += 1
            self.tok_num = int(self.text[self.pos:end], 16)
            self.pos = end
            self.tok = T_NUM
            return
        if c.isdigit():
            end = self.pos
            while end < len(self.text) and self.text[end].isdigit():
                end += 1
            self.tok_num = int(self.text[self.pos:end])
            self.pos = end
            self.tok = T_NUM
            return
        if c.isalpha() or c == '_':
            end = self.pos
            while end < len(self.text) and (self.text[end].isalnum() or self.text[end] == '_'):
                end += 1
            self.tok_id = self.text[self.pos:end]
            self.pos = end
            self.tok = T_ID
            return
        self.pos += 1
        if c == '+': self.tok = T_PLUS
        elif c == '-': self.tok = T_MINUS
        elif c == '*':
            if self.pos < len(self.text) and self.text[self.pos] == '*':
                self.pos += 1; self.tok = T_POW
            else: self.tok = T_MUL
        elif c == '/': self.tok = T_DIV
        elif c == '%': self.tok = T_MOD
        elif c == '&': self.tok = T_AND
        elif c == '|': self.tok = T_OR
        elif c == '^': self.tok = T_XOR
        elif c == '~': self.tok = T_NOT
        elif c == '<':
            if self.pos < len(self.text) and self.text[self.pos] == '<':
                self.pos += 1; self.tok = T_SHL
            else: self.tok = T_ERR
        elif c == '>':
            if self.pos < len(self.text) and self.text[self.pos] == '>':
                self.pos += 1; self.tok = T_SHR
            else: self.tok = T_ERR
        elif c == '#': self.tok = T_HASH
        elif c == '@': self.tok = T_ROT
        elif c == '$': self.tok = T_BYTE
        elif c == '(': self.tok = T_LP
        elif c == ')': self.tok = T_RP
        elif c == ',': self.tok = T_COMMA
        else: self.tok = T_ERR


def to_i64(x):
    x = x & MASK64
    if x >= (1 << 63):
        x -= (1 << 64)
    return x


def to_u32(x):
    return x & MASK32


# ── CRC32 ──

def crc32_compute(val):
    v = val & MASK32
    b = struct.pack('<I', v)
    crc = 0xFFFFFFFF
    for byte in b:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xEDB88320
            else:
                crc >>= 1
    return (crc ^ 0xFFFFFFFF) & MASK32


# ── Cipher (Feistel network) ──

def cipher_compute(val):
    v = val & MASK32
    left = (v >> 16) & 0xFFFF
    right = v & 0xFFFF
    for i in range(4):
        klo = FEISTEL_KEYS[i] & 0xFFFF
        khi = (FEISTEL_KEYS[i] >> 16) & 0xFFFF
        f = (((right * klo) >> 16) & 0xFFFF) ^ khi
        new_right = (left ^ f) & 0xFFFF
        left = right
        right = new_right
    return (left << 16) | right


# ── Built-in functions ──

def do_func(name, args):
    n = len(args)
    if name == "gcd" and n == 2:
        a, b = abs(args[0]), abs(args[1])
        while b:
            a, b = b, a % b
        return a
    if name == "lcm" and n == 2:
        if args[0] == 0 or args[1] == 0:
            return 0
        a, b = abs(args[0]), abs(args[1])
        g = a
        h = b
        while h:
            g, h = h, g % h
        return a // g * b
    if name == "fib" and n == 1:
        nn = args[0]
        if nn <= 0:
            return 0
        if nn == 1:
            return 1
        x, y = 0, 1
        for _ in range(2, nn + 1):
            x, y = y, x + y
        return y
    if name == "popcount" and n == 1:
        return bin(to_u32(args[0])).count('1')
    if name == "bitrev" and n == 1:
        v = to_u32(args[0])
        r = 0
        for _ in range(32):
            r = (r << 1) | (v & 1)
            v >>= 1
        return r
    if name == "crc32" and n == 1:
        return crc32_compute(args[0])
    if name == "cipher" and n == 1:
        return cipher_compute(args[0])
    if name == "abs" and n == 1:
        return abs(args[0])
    if name == "min" and n == 2:
        return min(args[0], args[1])
    if name == "max" and n == 2:
        return max(args[0], args[1])
    print("Error: unknown function", file=sys.stderr)
    return 0


# ── Parser ──
# Precedence (low -> high):
#  0: #  (hash combine)
#  1: |  (bitwise or)
#  2: ^  (bitwise xor)
#  3: &  (bitwise and)
#  4: << >>
#  5: + -
#  6: * / %
#  7: @ $  (rotate, byte-extract)
#  8: unary -
#  9: ** (right-assoc)
# 10: unary ~
# 11: primary

class Parser:
    def __init__(self, text):
        self.lex = Lexer(text)

    def parse(self):
        if self.lex.tok == T_END:
            return None
        return self.p_hash()

    def p_hash(self):
        left = self.p_bitor()
        while self.lex.tok == T_HASH:
            self.lex.advance()
            right = self.p_bitor()
            ua = to_u32(left)
            ub = to_u32(right)
            left = int(((ua * HASH_C) & MASK32) ^ ub)
        return left

    def p_bitor(self):
        left = self.p_bitxor()
        while self.lex.tok == T_OR:
            self.lex.advance()
            right = self.p_bitxor()
            left = int(to_u32(left) | to_u32(right))
        return left

    def p_bitxor(self):
        left = self.p_bitand()
        while self.lex.tok == T_XOR:
            self.lex.advance()
            right = self.p_bitand()
            left = int(to_u32(left) ^ to_u32(right))
        return left

    def p_bitand(self):
        left = self.p_shift()
        while self.lex.tok == T_AND:
            self.lex.advance()
            right = self.p_shift()
            left = int(to_u32(left) & to_u32(right))
        return left

    def p_shift(self):
        left = self.p_add()
        while self.lex.tok in (T_SHL, T_SHR):
            op = self.lex.tok
            self.lex.advance()
            right = self.p_add()
            v = to_u32(left)
            s = int(right) & 31
            if op == T_SHL:
                left = int((v << s) & MASK32)
            else:
                left = int(v >> s)
        return left

    def p_add(self):
        left = self.p_mul()
        while self.lex.tok in (T_PLUS, T_MINUS):
            op = self.lex.tok
            self.lex.advance()
            right = self.p_mul()
            if op == T_PLUS:
                left = to_i64(left + right)
            else:
                left = to_i64(left - right)
        return left

    def p_mul(self):
        left = self.p_custom()
        while self.lex.tok in (T_MUL, T_DIV, T_MOD):
            op = self.lex.tok
            self.lex.advance()
            right = self.p_custom()
            if op == T_MUL:
                left = to_i64(left * right)
            elif right == 0:
                left = 0
            elif op == T_DIV:
                sign = -1 if (left < 0) != (right < 0) else 1
                left = sign * (abs(left) // abs(right))
            else:
                sign = -1 if (left < 0) != (right < 0) else 1
                q = sign * (abs(left) // abs(right))
                left = left - q * right
        return left

    def p_custom(self):
        left = self.p_neg()
        while self.lex.tok in (T_ROT, T_BYTE):
            op = self.lex.tok
            self.lex.advance()
            right = self.p_neg()
            if op == T_ROT:
                v = to_u32(left)
                s = int(right) & 31
                if s:
                    left = int(((v << s) | (v >> (32 - s))) & MASK32)
                else:
                    left = int(v)
            else:
                v = to_u32(left)
                idx = int(right) & 3
                left = int((v >> (idx * 8)) & 0xFF)
        return left

    def p_neg(self):
        if self.lex.tok == T_MINUS:
            self.lex.advance()
            return to_i64(-self.p_neg())
        return self.p_power()

    def p_power(self):
        left = self.p_unary()
        if self.lex.tok == T_POW:
            self.lex.advance()
            right = self.p_neg()
            if right < 0:
                return 0
            return to_i64(pow(int(left), int(right), 2**64))
        return left

    def p_unary(self):
        if self.lex.tok == T_NOT:
            self.lex.advance()
            v = self.p_unary()
            return int((~to_u32(v)) & MASK32)
        return self.p_primary()

    def p_primary(self):
        if self.lex.tok == T_NUM:
            v = self.lex.tok_num
            self.lex.advance()
            return v
        if self.lex.tok == T_ID:
            name = self.lex.tok_id
            self.lex.advance()
            if self.lex.tok == T_LP:
                self.lex.advance()
                args = []
                if self.lex.tok != T_RP:
                    args.append(self.p_hash())
                    while self.lex.tok == T_COMMA:
                        self.lex.advance()
                        args.append(self.p_hash())
                if self.lex.tok == T_RP:
                    self.lex.advance()
                return do_func(name, args)
            print("Error: syntax error", file=sys.stderr)
            return 0
        if self.lex.tok == T_LP:
            self.lex.advance()
            v = self.p_hash()
            if self.lex.tok == T_RP:
                self.lex.advance()
            return v
        print("Error: syntax error", file=sys.stderr)
        return 0


# ── Output ──

def print_result(v, use_hex, use_bin):
    v = int(v)
    if use_hex:
        if v < 0:
            mag = (-v) & MASK64
            print(f"-0x{mag:x}")
        else:
            print(f"0x{v:x}")
    elif use_bin:
        if v == 0:
            print("0b0")
        elif v < 0:
            mag = (-v) & MASK64
            print(f"-0b{mag:b}")
        else:
            print(f"0b{v:b}")
    else:
        print(v)


def evaluate(text, use_hex, use_bin):
    p = Parser(text)
    result = p.parse()
    if result is None:
        return
    print_result(result, use_hex, use_bin)


def main():
    use_hex = False
    use_bin = False
    use_file = False
    arg = None

    args = sys.argv[1:]
    for a in args:
        if a == "-x":
            use_hex = True
        elif a == "-b":
            use_bin = True
        elif a == "-f":
            use_file = True
        else:
            arg = a

    if arg is None:
        print("Usage: myeval [-x|-b] [-f] <expr|file>", file=sys.stderr)
        sys.exit(1)

    if use_file:
        try:
            with open(arg) as f:
                for line in f:
                    line = line.rstrip('\n').rstrip('\r')
                    if not line or line[0] == '#':
                        continue
                    if not line.strip():
                        continue
                    evaluate(line, use_hex, use_bin)
        except FileNotFoundError:
            print("Error: cannot open file", file=sys.stderr)
            sys.exit(1)
    else:
        evaluate(arg, use_hex, use_bin)


if __name__ == "__main__":
    main()
