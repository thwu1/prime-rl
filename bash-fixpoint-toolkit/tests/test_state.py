
import subprocess
import pytest


def run(*args):
    """Run arith.sh with the given arguments and return the CompletedProcess."""
    return subprocess.run(
        ["bash", "/app/arith.sh"] + list(args),
        capture_output=True, text=True, timeout=30,
    )


# =====================================================================
# from_base — uses bash builtin, should all pass with the broken code
# =====================================================================

class TestFromBase:
    def test_binary(self):
        r = run("from_base", "2", "1010")
        assert r.returncode == 0
        assert r.stdout.strip() == "10"

    def test_hex_lowercase(self):
        r = run("from_base", "16", "ff")
        assert r.returncode == 0
        assert r.stdout.strip() == "255"

    def test_hex_uppercase_base36(self):
        """For bases <=36 uppercase == lowercase on input"""
        r = run("from_base", "16", "FF")
        assert r.returncode == 0
        assert r.stdout.strip() == "255"

    def test_base64_special(self):
        r = run("from_base", "64", "__")
        assert r.returncode == 0
        assert r.stdout.strip() == "4095"

    def test_base64_at(self):
        r = run("from_base", "64", "@")
        assert r.returncode == 0
        assert r.stdout.strip() == "62"

    def test_large_hex(self):
        r = run("from_base", "16", "deadbeef")
        assert r.returncode == 0
        assert r.stdout.strip() == "3735928559"


# =====================================================================
# to_base — exercises val_to_char, zero/negative handling
# =====================================================================

class TestToBaseDigitAlphabet:
    """The base-64 digit alphabet maps uppercase A-Z to values 36-61."""

    def test_value_36_is_A(self):
        r = run("to_base", "64", "36")
        assert r.returncode == 0
        assert r.stdout.strip() == "A"

    def test_value_61_is_Z(self):
        r = run("to_base", "64", "61")
        assert r.returncode == 0
        assert r.stdout.strip() == "Z"

    def test_value_62_is_at(self):
        r = run("to_base", "64", "62")
        assert r.returncode == 0
        assert r.stdout.strip() == "@"

    def test_value_63_is_underscore(self):
        r = run("to_base", "64", "63")
        assert r.returncode == 0
        assert r.stdout.strip() == "_"

    def test_4095_double_underscore(self):
        """63*64+63 = 4095 = '__'"""
        r = run("to_base", "64", "4095")
        assert r.returncode == 0
        assert r.stdout.strip() == "__"

    def test_4094_underscore_at(self):
        """63*64+62 = 4094 = '_@'"""
        r = run("to_base", "64", "4094")
        assert r.returncode == 0
        assert r.stdout.strip() == "_@"

    def test_roundtrip_base64(self):
        """from_base then to_base should roundtrip for mixed-case base-64."""
        r1 = run("from_base", "64", "aZ@_")
        assert r1.returncode == 0
        decimal = r1.stdout.strip()
        r2 = run("to_base", "64", decimal)
        assert r2.returncode == 0
        assert r2.stdout.strip() == "aZ@_"


class TestToBaseEdgeCases:
    def test_zero(self):
        r = run("to_base", "16", "0")
        assert r.returncode == 0
        assert r.stdout.strip() == "0"

    def test_zero_base2(self):
        r = run("to_base", "2", "0")
        assert r.returncode == 0
        assert r.stdout.strip() == "0"

    def test_negative_hex(self):
        r = run("to_base", "16", "-255")
        assert r.returncode == 0
        assert r.stdout.strip() == "-ff"

    def test_negative_binary(self):
        r = run("to_base", "2", "-10")
        assert r.returncode == 0
        assert r.stdout.strip() == "-1010"

    def test_simple_hex(self):
        r = run("to_base", "16", "255")
        assert r.returncode == 0
        assert r.stdout.strip() == "ff"

    def test_simple_binary(self):
        r = run("to_base", "2", "10")
        assert r.returncode == 0
        assert r.stdout.strip() == "1010"


# =====================================================================
# base_convert — combines from_base + to_base
# =====================================================================

class TestBaseConvert:
    def test_hex_to_binary(self):
        r = run("base_convert", "16", "2", "ff")
        assert r.returncode == 0
        assert r.stdout.strip() == "11111111"

    def test_binary_to_octal(self):
        r = run("base_convert", "2", "8", "111111")
        assert r.returncode == 0
        assert r.stdout.strip() == "77"

    def test_decimal_to_base64_uppercase(self):
        """Converting 36 to base 64 must produce 'A'"""
        r = run("base_convert", "10", "64", "36")
        assert r.returncode == 0
        assert r.stdout.strip() == "A"

    def test_base64_roundtrip(self):
        r = run("base_convert", "64", "10", "__")
        assert r.returncode == 0
        assert r.stdout.strip() == "4095"

    def test_hex_deadbeef_to_decimal(self):
        r = run("base_convert", "16", "10", "deadbeef")
        assert r.returncode == 0
        assert r.stdout.strip() == "3735928559"


# =====================================================================
# Fixed-point addition — exercises fp_parse padding
# =====================================================================

class TestFpAdd:
    def test_matching_precision(self):
        """Frac digits == precision: no padding needed"""
        r = run("fp_add", "1.25", "3.75", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "5.00"

    def test_short_frac_prec2(self):
        """'1.5' at prec 2 must be 1.50, not 1.05"""
        r = run("fp_add", "1.5", "1.5", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "3.00"

    def test_short_frac_prec4(self):
        """'0.5' at prec 4 must be 0.5000"""
        r = run("fp_add", "0.5", "0.5", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "1.0000"

    def test_no_fraction(self):
        r = run("fp_add", "10", "20", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "30.00"

    def test_negative(self):
        r = run("fp_add", "5.5", "-3.2", "1")
        assert r.returncode == 0
        assert r.stdout.strip() == "2.3"

    def test_both_negative(self):
        r = run("fp_add", "-1.25", "-3.75", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "-5.00"


# =====================================================================
# Fixed-point multiplication — exercises overflow splitting
# =====================================================================

class TestFpMul:
    def test_simple(self):
        r = run("fp_mul", "2.50", "4.00", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "10.00"

    def test_precision(self):
        r = run("fp_mul", "1.2345", "6.7890", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "8.3810"

    def test_overflow_safe(self):
        """400000.0000 * 400000.0000: naive a*b overflows 64-bit"""
        r = run("fp_mul", "400000.0000", "400000.0000", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "160000000000.0000"

    def test_negative(self):
        r = run("fp_mul", "-3.00", "5.00", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "-15.00"

    def test_fractional_padding_in_mul(self):
        """'2.5' at prec 2 must be parsed as 250, not 205"""
        r = run("fp_mul", "2.5", "2.5", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "6.25"


# =====================================================================
# Fixed-point division — exercises overflow splitting
# =====================================================================

class TestFpDiv:
    def test_simple(self):
        r = run("fp_div", "7.50", "2.50", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "3.00"

    def test_truncation(self):
        r = run("fp_div", "10.00", "3.00", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "3.33"

    def test_overflow_safe(self):
        """500000000000.0000 / 2.0000: naive a*scale overflows 64-bit"""
        r = run("fp_div", "500000000000.0000", "2.0000", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "250000000000.0000"

    def test_div_by_zero(self):
        r = run("fp_div", "1.00", "0.00", "2")
        assert r.returncode != 0

    def test_negative_division(self):
        r = run("fp_div", "-9.00", "3.00", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "-3.00"


# =====================================================================
# Fixed-point square root — exercises scaling and overflow-safe Newton
# =====================================================================

class TestFpSqrt:
    def test_perfect_square_4(self):
        """sqrt(4) = 2: catches the val-vs-val*scale scaling bug"""
        r = run("fp_sqrt", "4.0000", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "2.0000"

    def test_sqrt_9(self):
        r = run("fp_sqrt", "9.0000", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "3.0000"

    def test_sqrt_2(self):
        """sqrt(2) truncated at 4 places"""
        r = run("fp_sqrt", "2.0000", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "1.4142"

    def test_zero(self):
        r = run("fp_sqrt", "0.0000", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "0.0000"

    def test_negative_error(self):
        r = run("fp_sqrt", "-4.0000", "4")
        assert r.returncode != 0

    def test_sqrt_quarter(self):
        """sqrt(0.25) = 0.5"""
        r = run("fp_sqrt", "0.2500", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "0.5000"

    def test_perfect_square_large(self):
        """sqrt(1000000) = 1000"""
        r = run("fp_sqrt", "1000000.0000", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "1000.0000"

    def test_prec2(self):
        """sqrt(2) at precision 2"""
        r = run("fp_sqrt", "2.00", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "1.41"

    def test_overflow_safe(self):
        """sqrt(100000000000): val*scale overflows 64-bit, must use splitting"""
        r = run("fp_sqrt", "100000000000.0000", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "316227.7660"

    def test_sqrt_one(self):
        r = run("fp_sqrt", "1.0000", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "1.0000"

    def test_fractional_padding(self):
        """'0.25' at prec 4 must be right-padded to 0.2500 before sqrt"""
        r = run("fp_sqrt", "0.25", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "0.5000"

    def test_small_value(self):
        """sqrt(0.0001) = 0.01"""
        r = run("fp_sqrt", "0.0001", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "0.0100"


# =====================================================================
# Fixed-point exponentiation — exercises overflow-safe power
# =====================================================================

class TestFpPow:
    def test_square(self):
        r = run("fp_pow", "3.00", "2", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "9.00"

    def test_cube(self):
        r = run("fp_pow", "2.00", "3", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "8.00"

    def test_exp_zero(self):
        r = run("fp_pow", "5.00", "0", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "1.00"

    def test_exp_one(self):
        r = run("fp_pow", "7.50", "1", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "7.50"

    def test_overflow_safe(self):
        """4000000.0000 ^ 2: naive result*base overflows 64-bit"""
        r = run("fp_pow", "4000000.0000", "2", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "16000000000000.0000"

    def test_negative_base_odd(self):
        r = run("fp_pow", "-2.00", "3", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "-8.00"

    def test_negative_base_even(self):
        r = run("fp_pow", "-2.00", "4", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "16.00"

    def test_fractional_base(self):
        """0.5^3 = 0.125, truncated at prec 2 = 0.12"""
        r = run("fp_pow", "0.50", "3", "2")
        assert r.returncode == 0
        assert r.stdout.strip() == "0.12"

    def test_precision4(self):
        """1.5^4 = 5.0625"""
        r = run("fp_pow", "1.5000", "4", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "5.0625"

    def test_frac_padding(self):
        """'1.5' at prec 4 must be right-padded before exponentiation"""
        r = run("fp_pow", "1.5", "2", "4")
        assert r.returncode == 0
        assert r.stdout.strip() == "2.2500"


# =====================================================================
# Sanitize — exercises signed-number 10# pitfall
# =====================================================================

class TestSanitize:
    def test_leading_zero(self):
        r = run("sanitize", "09")
        assert r.returncode == 0
        assert r.stdout.strip() == "9"

    def test_octal_like(self):
        r = run("sanitize", "007")
        assert r.returncode == 0
        assert r.stdout.strip() == "7"

    def test_normal(self):
        r = run("sanitize", "42")
        assert r.returncode == 0
        assert r.stdout.strip() == "42"

    def test_negative_leading_zero(self):
        """10#-019 is a known bash pitfall; must handle sign separately"""
        r = run("sanitize", "-019")
        assert r.returncode == 0
        assert r.stdout.strip() == "-19"

    def test_plus_prefix(self):
        r = run("sanitize", "+008")
        assert r.returncode == 0
        assert r.stdout.strip() == "8"

    def test_zero(self):
        r = run("sanitize", "0")
        assert r.returncode == 0
        assert r.stdout.strip() == "0"

    def test_padded_zero(self):
        r = run("sanitize", "000")
        assert r.returncode == 0
        assert r.stdout.strip() == "0"
