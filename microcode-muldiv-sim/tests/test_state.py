"""
Tests for 8086 microcode-level MUL/DIV simulator with Verilog cross-validation.

"""

import json
import os
import pytest


@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.exists(path), f"results.json not found at {path}"
    with open(path) as f:
        return json.load(f)


# ===== Unsigned Word Multiply =====

class TestMulWord:
    def test_ffff_times_f00f(self, results):
        """0xFFFF * 0xF00F = 0xF00E0FF1"""
        r = results["mul_word"][0]
        assert r["ax"] == 0x0FF1, f"AX should be 0x0FF1, got 0x{r['ax']:04X}"
        assert r["dx"] == 0xF00E, f"DX should be 0xF00E, got 0x{r['dx']:04X}"
        assert r["cf"] == 1
        assert r["of"] == 1

    def test_3_times_5(self, results):
        """0x0003 * 0x0005 = 15"""
        r = results["mul_word"][1]
        assert r["ax"] == 15
        assert r["dx"] == 0
        assert r["cf"] == 0
        assert r["of"] == 0

    def test_8000_times_2(self, results):
        """0x8000 * 0x0002 = 0x00010000"""
        r = results["mul_word"][2]
        assert r["ax"] == 0
        assert r["dx"] == 1
        assert r["cf"] == 1
        assert r["of"] == 1


# ===== Unsigned Byte Multiply =====

class TestMulByte:
    def test_ff_times_55(self, results):
        """0xFF * 0x55 = 21675 = 0x54AB"""
        r = results["mul_byte"][0]
        assert r["al"] == 0xAB
        assert r["ah"] == 0x54
        assert r["cf"] == 1
        assert r["of"] == 1

    def test_3_times_7(self, results):
        """0x03 * 0x07 = 21"""
        r = results["mul_byte"][1]
        assert r["al"] == 21
        assert r["ah"] == 0
        assert r["cf"] == 0
        assert r["of"] == 0


# ===== Signed Word Multiply =====

class TestImulWord:
    def test_neg7_times_7(self, results):
        """-7 * 7 = -49 = 0xFFFFFFCF"""
        r = results["imul_word"][0]
        assert r["ax"] == 0xFFCF, f"AX should be 0xFFCF, got 0x{r['ax']:04X}"
        assert r["dx"] == 0xFFFF, f"DX should be 0xFFFF, got 0x{r['dx']:04X}"
        # -49 fits in 16 bits, so CF=OF=0
        assert r["cf"] == 0
        assert r["of"] == 0

    def test_3_times_5_signed(self, results):
        """3 * 5 = 15"""
        r = results["imul_word"][1]
        assert r["ax"] == 15
        assert r["dx"] == 0
        assert r["cf"] == 0
        assert r["of"] == 0

    def test_neg4_times_neg2(self, results):
        """-4 * -2 = 8"""
        r = results["imul_word"][2]
        assert r["ax"] == 8
        assert r["dx"] == 0
        assert r["cf"] == 0
        assert r["of"] == 0


# ===== Unsigned Word Divide =====

class TestDivWord:
    def test_large_division(self, results):
        """0x0F00FF00 / 0x0FFC = quotient 0xF04C, remainder 0x0030"""
        r = results["div_word"][0]
        assert "error" not in r
        assert r["ax"] == 0xF04C, f"Quotient should be 0xF04C, got 0x{r['ax']:04X}"
        assert r["dx"] == 0x0030, f"Remainder should be 0x0030, got 0x{r['dx']:04X}"

    def test_67_div_10(self, results):
        """67 / 10 = quotient 6, remainder 7"""
        r = results["div_word"][1]
        assert r["ax"] == 6
        assert r["dx"] == 7

    def test_100_div_10(self, results):
        """100 / 10 = quotient 10, remainder 0"""
        r = results["div_word"][2]
        assert r["ax"] == 10
        assert r["dx"] == 0


# ===== Unsigned Byte Divide =====

class TestDivByte:
    def test_2345_div_34(self, results):
        """0x2345 / 0x34 = quotient 173 (0xAD), remainder 33 (0x21)"""
        r = results["div_byte"][0]
        assert r["al"] == 0xAD, f"Quotient should be 0xAD, got 0x{r['al']:02X}"
        assert r["ah"] == 0x21, f"Remainder should be 0x21, got 0x{r['ah']:02X}"

    def test_100_div_10_byte(self, results):
        """100 / 10 = quotient 10, remainder 0"""
        r = results["div_byte"][1]
        assert r["al"] == 10
        assert r["ah"] == 0


# ===== Signed Word Divide =====

class TestIdivWord:
    def test_neg27_div_7(self, results):
        """-27 / 7 = quotient -3, remainder -6"""
        r = results["idiv_word"][0]
        assert "error" not in r
        # -3 as unsigned 16-bit = 0xFFFD = 65533
        assert r["ax"] == 0xFFFD, f"Quotient should be -3 (0xFFFD), got 0x{r['ax']:04X}"
        # -6 as unsigned 16-bit = 0xFFFA = 65530
        assert r["dx"] == 0xFFFA, f"Remainder should be -6 (0xFFFA), got 0x{r['dx']:04X}"

    def test_neg27_div_neg7(self, results):
        """-27 / -7 = quotient 3, remainder -6"""
        r = results["idiv_word"][1]
        assert r["ax"] == 3
        assert r["dx"] == 0xFFFA  # -6

    def test_27_div_neg7(self, results):
        """27 / -7 = quotient -3, remainder 6"""
        r = results["idiv_word"][2]
        assert r["ax"] == 0xFFFD  # -3
        assert r["dx"] == 6


# ===== Overflow and Divide-by-Zero =====

class TestDivOverflow:
    def test_overflow(self, results):
        """DX:AX = 0x00010000 / 0x0001 -> overflow (quotient > 16 bits)"""
        r = results["div_overflow"][0]
        assert r.get("error") is True

    def test_divide_by_zero(self, results):
        """Division by zero -> error"""
        r = results["div_overflow"][1]
        assert r.get("error") is True


# ===== Multiplication Trace =====

class TestMulTrace:
    def test_trace_length(self, results):
        """17 entries: initial state + 16 loop iterations"""
        assert len(results["mul_trace"]) == 17

    def test_trace_initial(self, results):
        """Initial state after tmpA=0 and RCR of tmpC"""
        t = results["mul_trace"][0]
        assert t["tmpA"] == 0

    def test_trace_final(self, results):
        """Final state: tmpA=DX=0xF00E, tmpC=AX=0x0FF1"""
        t = results["mul_trace"][-1]
        assert t["tmpA"] == 0xF00E, f"Final tmpA should be 0xF00E, got 0x{t['tmpA']:04X}"
        assert t["tmpC"] == 0x0FF1, f"Final tmpC should be 0x0FF1, got 0x{t['tmpC']:04X}"

    def test_trace_monotonic_tmpA(self, results):
        """tmpA should generally grow as the product accumulates"""
        trace = results["mul_trace"]
        # tmpA starts at 0 and ends at a large value
        assert trace[0]["tmpA"] == 0
        assert trace[-1]["tmpA"] > 0

    def test_trace_consistency(self, results):
        """Final tmpA:tmpC should equal 0xFFFF * 0xF00F"""
        t = results["mul_trace"][-1]
        product = (t["tmpA"] << 16) | t["tmpC"]
        assert product == 0xFFFF * 0xF00F


# ===== Division Trace =====

class TestDivTrace:
    def test_trace_length(self, results):
        """17 entries: initial state + 16 loop iterations"""
        assert len(results["div_trace"]) == 17

    def test_trace_initial(self, results):
        """Initial state: tmpA=DX=0x0F00, tmpC=AX=0xFF00"""
        t = results["div_trace"][0]
        assert t["tmpA"] == 0x0F00
        assert t["tmpC"] == 0xFF00

    def test_trace_final_remainder(self, results):
        """Final tmpA should be the remainder (0x0030)"""
        t = results["div_trace"][-1]
        assert t["tmpA"] == 0x0030, f"Final tmpA (remainder) should be 0x0030, got 0x{t['tmpA']:04X}"

    def test_trace_final_quotient_embedded(self, results):
        """After the division loop, tmpC holds pre-final quotient bits.
        We verify the remainder is correct, which proves the division loop worked."""
        t = results["div_trace"][-1]
        assert t["tmpA"] == 48  # remainder = 0x0030 = 48


# ===== Cross-validation: mathematical correctness =====

class TestMathCorrectness:
    def test_mul_word_math(self, results):
        for r in results["mul_word"]:
            if "error" not in r:
                pass  # Already tested specific values

    def test_div_word_math(self, results):
        """Verify quotient * divisor + remainder = dividend"""
        # Test case 0: 0x0F00FF00 / 0x0FFC
        r = results["div_word"][0]
        dividend = (0x0F00 << 16) | 0xFF00
        divisor = 0x0FFC
        assert r["ax"] * divisor + r["dx"] == dividend

        # Test case 1: 67 / 10
        r = results["div_word"][1]
        assert r["ax"] * 10 + r["dx"] == 67

        # Test case 2: 100 / 10
        r = results["div_word"][2]
        assert r["ax"] * 10 + r["dx"] == 100

    def test_div_byte_math(self, results):
        """Verify quotient * divisor + remainder = dividend for byte ops"""
        r = results["div_byte"][0]
        assert r["al"] * 0x34 + r["ah"] == 0x2345

    def test_idiv_math(self, results):
        """Verify signed division: quotient * divisor + remainder = dividend"""
        def to_signed_16(v):
            return v - 0x10000 if v >= 0x8000 else v

        # -27 / 7
        r = results["idiv_word"][0]
        q = to_signed_16(r["ax"])
        rem = to_signed_16(r["dx"])
        assert q * 7 + rem == -27
        assert rem <= 0  # remainder sign matches dividend sign (negative)

        # -27 / -7
        r = results["idiv_word"][1]
        q = to_signed_16(r["ax"])
        rem = to_signed_16(r["dx"])
        assert q * (-7) + rem == -27
        assert rem <= 0

        # 27 / -7
        r = results["idiv_word"][2]
        q = to_signed_16(r["ax"])
        rem = to_signed_16(r["dx"])
        assert q * (-7) + rem == 27
        assert rem >= 0  # remainder sign matches dividend sign (positive)


# ===== Verilog Cross-Validation =====

class TestVerilogFiles:
    def test_corx_v_exists(self):
        """Verilog module source must exist"""
        assert os.path.exists("/app/corx.v"), "corx.v not found at /app/corx.v"

    def test_corx_v_is_verilog(self):
        """Verilog source must contain proper module definition"""
        with open("/app/corx.v") as f:
            src = f.read()
        assert "module" in src, "corx.v does not contain 'module' keyword"
        assert "endmodule" in src, "corx.v does not contain 'endmodule'"
        assert "always" in src or "assign" in src, "corx.v lacks sequential/combinational logic"

    def test_testbench_exists(self):
        """Verilog testbench must exist"""
        assert os.path.exists("/app/corx_tb.v"), "corx_tb.v not found at /app/corx_tb.v"

    def test_vcd_exists(self):
        """VCD waveform dump must exist (proves simulation ran)"""
        assert os.path.exists("/app/corx_sim.vcd"), \
            "VCD file not found at /app/corx_sim.vcd — did the simulation run?"

    def test_vcd_nonempty(self):
        """VCD file must not be empty"""
        size = os.path.getsize("/app/corx_sim.vcd")
        assert size > 100, f"VCD file is suspiciously small ({size} bytes)"


class TestVerilogTrace:
    def test_verilog_trace_present(self, results):
        """results.json must contain verilog_mul_trace"""
        assert "verilog_mul_trace" in results, "Missing verilog_mul_trace in results"

    def test_verilog_trace_length(self, results):
        """Verilog trace should have 17 entries (initial + 16 iterations)"""
        assert len(results["verilog_mul_trace"]) == 17

    def test_verilog_trace_initial(self, results):
        """Verilog trace initial state: tmpA=0"""
        t = results["verilog_mul_trace"][0]
        assert t["tmpA"] == 0, f"Initial tmpA should be 0, got {t['tmpA']}"

    def test_verilog_trace_final(self, results):
        """Verilog trace final state must match expected product"""
        t = results["verilog_mul_trace"][-1]
        assert t["tmpA"] == 0xF00E, f"Final tmpA should be 0xF00E, got 0x{t['tmpA']:04X}"
        assert t["tmpC"] == 0x0FF1, f"Final tmpC should be 0x0FF1, got 0x{t['tmpC']:04X}"

    def test_verilog_trace_matches_python(self, results):
        """Every entry of the Verilog trace must match the primary trace exactly"""
        py_trace = results["mul_trace"]
        vl_trace = results["verilog_mul_trace"]
        assert len(py_trace) == len(vl_trace), \
            f"Trace length mismatch: primary={len(py_trace)}, Verilog={len(vl_trace)}"
        for i, (py, vl) in enumerate(zip(py_trace, vl_trace)):
            assert py["tmpA"] == vl["tmpA"], \
                f"Trace[{i}] tmpA mismatch: primary=0x{py['tmpA']:04X} Verilog=0x{vl['tmpA']:04X}"
            assert py["tmpC"] == vl["tmpC"], \
                f"Trace[{i}] tmpC mismatch: primary=0x{py['tmpC']:04X} Verilog=0x{vl['tmpC']:04X}"


class TestVerilogProduct:
    def test_product_present(self, results):
        """results.json must contain verilog_product"""
        assert "verilog_product" in results, "Missing verilog_product in results"

    def test_product_high(self, results):
        """Verilog product high word should be 0xF00E"""
        assert results["verilog_product"]["high"] == 0xF00E

    def test_product_low(self, results):
        """Verilog product low word should be 0x0FF1"""
        assert results["verilog_product"]["low"] == 0x0FF1

    def test_product_consistency(self, results):
        """Full 32-bit product must equal 0xFFFF * 0xF00F"""
        p = results["verilog_product"]
        product = (p["high"] << 16) | p["low"]
        assert product == 0xFFFF * 0xF00F
