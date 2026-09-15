
import subprocess
import os
import tempfile
import pytest

MYEVAL = "/app/myeval"


def run_eval(expr, flags=None):
    """Run myeval with expression, return stdout stripped."""
    cmd = [MYEVAL]
    if flags:
        cmd.extend(flags)
    cmd.append(expr)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return r.stdout.strip()


def run_eval_file(lines, flags=None):
    """Run myeval -f with a temp file, return stdout stripped."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("\n".join(lines) + "\n")
        fname = f.name
    try:
        cmd = [MYEVAL, "-f"]
        if flags:
            cmd.extend(flags)
        cmd.append(fname)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    finally:
        os.unlink(fname)


# ── Basic arithmetic ──

class TestBasicArithmetic:
    def test_add(self):
        assert run_eval("2 + 3") == "5"

    def test_subtract(self):
        assert run_eval("10 - 3") == "7"

    def test_multiply(self):
        assert run_eval("4 * 5") == "20"

    def test_divide_positive(self):
        assert run_eval("17 / 3") == "5"

    def test_modulo_positive(self):
        assert run_eval("17 % 3") == "2"

    def test_divide_negative(self):
        assert run_eval("-17 / 3") == "-5"

    def test_modulo_negative(self):
        assert run_eval("-17 % 3") == "-2"

    def test_divide_by_zero(self):
        assert run_eval("1 / 0") == "0"

    def test_modulo_by_zero(self):
        assert run_eval("5 % 0") == "0"

    def test_complex_arithmetic(self):
        assert run_eval("2 + 3 * 4 - 1") == "13"

    def test_parentheses(self):
        assert run_eval("(2 + 3) * (4 - 1)") == "15"


# ── Power operator ──

class TestPower:
    def test_power_basic(self):
        assert run_eval("2 ** 10") == "1024"

    def test_power_zero_exp(self):
        assert run_eval("3 ** 0") == "1"

    def test_power_zero_base_zero_exp(self):
        assert run_eval("0 ** 0") == "1"

    def test_power_negative_exp(self):
        assert run_eval("2 ** -1") == "0"

    def test_power_right_associative(self):
        assert run_eval("2 ** 3 ** 2") == "512"


# ── Operator precedence ──

class TestPrecedence:
    def test_mul_before_add(self):
        assert run_eval("2 + 3 * 4") == "14"

    def test_parens_override(self):
        assert run_eval("(2 + 3) * 4") == "20"

    def test_unary_neg_vs_power(self):
        assert run_eval("-3 ** 2") == "-9"

    def test_neg_in_parens_vs_power(self):
        assert run_eval("(-3) ** 2") == "9"

    def test_bitwise_not_vs_power(self):
        assert run_eval("~3 ** 2") == "-34359738352"


# ── Bitwise operations (32-bit) ──

class TestBitwise:
    def test_not_zero(self):
        assert run_eval("~0") == "4294967295"

    def test_not_one(self):
        assert run_eval("~1") == "4294967294"

    def test_and(self):
        assert run_eval("0xFF & 0x0F") == "15"

    def test_or(self):
        assert run_eval("0xFF | 0x100") == "511"

    def test_xor(self):
        assert run_eval("0xAA ^ 0x55") == "255"

    def test_shift_left(self):
        assert run_eval("1 << 10") == "1024"

    def test_shift_right(self):
        assert run_eval("1024 >> 3") == "128"

    def test_shift_left_31(self):
        assert run_eval("1 << 31") == "2147483648"

    def test_shift_right_16(self):
        assert run_eval("0xFFFFFFFF >> 16") == "65535"

    def test_bitwise_32bit_semantics(self):
        assert run_eval("~0 + 1") == "4294967296"


# ── Custom operator: hash (#) ──

class TestHashOperator:
    def test_hash_identity(self):
        assert run_eval("0 # 5") == "5"

    def test_hash_single(self):
        assert run_eval("1 # 0") == "2654435761"

    def test_hash_combine(self):
        assert run_eval("5 # 3") == "387276918"

    def test_hash_chained(self):
        assert run_eval("1 # 2 # 3") == "1012252608"


# ── Custom operator: rotate (@) ──

class TestRotateOperator:
    def test_rotate_1(self):
        assert run_eval("1 @ 1") == "2"

    def test_rotate_31(self):
        assert run_eval("1 @ 31") == "2147483648"

    def test_rotate_wrap(self):
        assert run_eval("0x80000000 @ 1") == "1"

    def test_rotate_zero_shift(self):
        assert run_eval("42 @ 0") == "42"

    def test_rotate_full(self):
        assert run_eval("42 @ 32") == "42"


# ── Custom operator: byte extract ($) ──

class TestByteExtract:
    def test_byte0(self):
        assert run_eval("0xDEADBEEF $ 0") == "239"

    def test_byte1(self):
        assert run_eval("0xDEADBEEF $ 1") == "190"

    def test_byte2(self):
        assert run_eval("0xDEADBEEF $ 2") == "173"

    def test_byte3(self):
        assert run_eval("0xDEADBEEF $ 3") == "222"

    def test_byte_index_wraps(self):
        assert run_eval("0xDEADBEEF $ 4") == "239"


# ── Built-in functions ──

class TestFunctions:
    def test_gcd_basic(self):
        assert run_eval("gcd(12, 8)") == "4"

    def test_gcd_coprime(self):
        assert run_eval("gcd(7, 13)") == "1"

    def test_gcd_with_zero(self):
        assert run_eval("gcd(0, 5)") == "5"

    def test_lcm_basic(self):
        assert run_eval("lcm(4, 6)") == "12"

    def test_lcm_with_zero(self):
        assert run_eval("lcm(0, 5)") == "0"

    def test_fib_zero(self):
        assert run_eval("fib(0)") == "0"

    def test_fib_one(self):
        assert run_eval("fib(1)") == "1"

    def test_fib_ten(self):
        assert run_eval("fib(10)") == "55"

    def test_fib_twenty(self):
        assert run_eval("fib(20)") == "6765"

    def test_fib_negative(self):
        assert run_eval("fib(-1)") == "0"

    def test_popcount_zero(self):
        assert run_eval("popcount(0)") == "0"

    def test_popcount_0xff(self):
        assert run_eval("popcount(255)") == "8"

    def test_popcount_one(self):
        assert run_eval("popcount(1)") == "1"

    def test_bitrev_one(self):
        assert run_eval("bitrev(1)") == "2147483648"

    def test_bitrev_high(self):
        assert run_eval("bitrev(0x80000000)") == "1"

    def test_crc32_zero(self):
        assert run_eval("crc32(0)") == "558161692"

    def test_crc32_one(self):
        assert run_eval("crc32(1)") == "2583214201"

    def test_crc32_large(self):
        assert run_eval("crc32(0xDEADBEEF)") == "442130463"

    def test_abs_negative(self):
        assert run_eval("abs(-42)") == "42"

    def test_abs_positive(self):
        assert run_eval("abs(42)") == "42"

    def test_min(self):
        assert run_eval("min(3, 7)") == "3"

    def test_max(self):
        assert run_eval("max(3, 7)") == "7"


# ── Cipher function (Feistel network with embedded keys) ──

class TestCipher:
    def test_cipher_zero(self):
        assert run_eval("cipher(0)") == "3801571057"

    def test_cipher_one(self):
        assert run_eval("cipher(1)") == "3801571056"

    def test_cipher_small(self):
        assert run_eval("cipher(42)") == "3803143923"

    def test_cipher_deadbeef(self):
        assert run_eval("cipher(0xDEADBEEF)") == "4197638635"

    def test_cipher_large(self):
        assert run_eval("cipher(0x12345678)") == "2430583101"

    def test_cipher_max(self):
        assert run_eval("cipher(0xFFFFFFFF)") == "2696104357"

    def test_cipher_hex_output(self):
        assert run_eval("cipher(0)", flags=["-x"]) == "0xe2975ef1"

    def test_cipher_composed(self):
        assert run_eval("cipher(cipher(0))") == "1913512488"


# ── Nested function calls ──

class TestNestedFunctions:
    def test_gcd_of_fibs(self):
        assert run_eval("gcd(fib(6), fib(8))") == "1"

    def test_popcount_of_bitwise(self):
        assert run_eval("popcount(0xFF & 0xAA)") == "4"

    def test_abs_of_negative_expr(self):
        assert run_eval("abs(3 - 10)") == "7"


# ── Output formats ──

class TestOutputFormats:
    def test_hex_positive(self):
        assert run_eval("255", flags=["-x"]) == "0xff"

    def test_hex_zero(self):
        assert run_eval("0", flags=["-x"]) == "0x0"

    def test_hex_negative(self):
        assert run_eval("0 - 1", flags=["-x"]) == "-0x1"

    def test_hex_large(self):
        assert run_eval("0xDEAD", flags=["-x"]) == "0xdead"

    def test_bin_positive(self):
        assert run_eval("10", flags=["-b"]) == "0b1010"

    def test_bin_zero(self):
        assert run_eval("0", flags=["-b"]) == "0b0"

    def test_bin_negative(self):
        assert run_eval("0 - 3", flags=["-b"]) == "-0b11"


# ── File mode ──

class TestFileMode:
    def test_file_basic(self):
        result = run_eval_file(["2 + 3", "10 * 5", "7 - 2"])
        assert result == "5\n50\n5"

    def test_file_skip_comments(self):
        result = run_eval_file(["# this is a comment", "2 + 3", "# another", "4 * 5"])
        assert result == "5\n20"

    def test_file_skip_empty(self):
        result = run_eval_file(["2 + 3", "", "4 * 5"])
        assert result == "5\n20"

    def test_file_with_hex_flag(self):
        result = run_eval_file(["255", "16"], flags=["-x"])
        assert result == "0xff\n0x10"


# ── Edge cases ──

class TestEdgeCases:
    def test_hex_literal(self):
        assert run_eval("0xFF") == "255"

    def test_large_hex(self):
        assert run_eval("0xDEADBEEF") == "3735928559"

    def test_nested_parens(self):
        assert run_eval("((((5))))") == "5"

    def test_double_negation(self):
        assert run_eval("--5") == "5"

    def test_complex_expression(self):
        assert run_eval("(2 + 3) @ 1") == "10"
