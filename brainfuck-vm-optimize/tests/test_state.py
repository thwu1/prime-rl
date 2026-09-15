
import subprocess
import os
import signal
import time
import tempfile

BFVM = "/app/bfvm"
TESTDATA = "/app/testdata"


def run_bf(filename, timeout=10, stdin_data=None):
    """Run a BF program and return (stdout_bytes, returncode, timed_out)."""
    filepath = os.path.join(TESTDATA, filename)
    try:
        result = subprocess.run(
            [BFVM, filepath],
            capture_output=True,
            timeout=timeout,
            input=stdin_data,
        )
        return result.stdout, result.returncode, False
    except subprocess.TimeoutExpired:
        return b"", -1, True


def run_bf_code(bf_code, timeout=10, stdin_data=None):
    """Run inline BF code and return (stdout_bytes, returncode, timed_out)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".b", delete=False) as f:
        f.write(bf_code)
        tmppath = f.name
    try:
        result = subprocess.run(
            [BFVM, tmppath],
            capture_output=True,
            timeout=timeout,
            input=stdin_data,
        )
        return result.stdout, result.returncode, False
    except subprocess.TimeoutExpired:
        return b"", -1, True
    finally:
        os.unlink(tmppath)


def dump_instructions(bf_code):
    """Write bf_code to a temp file, run bfvm -dump, return instruction list."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".b", delete=False) as f:
        f.write(bf_code)
        f.flush()
        tmppath = f.name
    try:
        result = subprocess.run(
            [BFVM, "-dump", tmppath],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip().split("\n")
    finally:
        os.unlink(tmppath)


# =========================================================================
# Correctness tests — bugs must be fixed for these to pass
# =========================================================================

class TestCorrectness:
    def test_hello_world(self):
        """Hello World requires correct nested loop bracket matching."""
        out, rc, timeout = run_bf("hello_world.b")
        assert not timeout, "hello_world.b timed out"
        assert rc == 0, f"hello_world.b exited with code {rc}"
        assert out == b"Hello World!\n", f"Wrong output: {out!r}"

    def test_nested_loops(self):
        """Nested loop test: 8*1*8 + 1 = 65 = 'A'."""
        out, rc, timeout = run_bf("nested.b")
        assert not timeout, "nested.b timed out"
        assert rc == 0, f"nested.b exited with code {rc}"
        assert out == b"A\n", f"Wrong output: {out!r}"

    def test_cell_underflow_wrapping(self):
        """Cell underflow: 0-3 should wrap to 253, clear loop must terminate."""
        out, rc, timeout = run_bf("cell_wrap.b", timeout=5)
        assert not timeout, (
            "cell_wrap.b timed out — cell wrapping bug causes infinite loop "
            "when underflowed cell enters [-] clear loop"
        )
        assert rc == 0, f"cell_wrap.b exited with code {rc}"
        assert out == b"B\n", f"Wrong output: {out!r}"

    def test_cell_overflow_wrapping(self):
        """Cell overflow: values above 255 must wrap modulo 256."""
        # Program: add 258 to cell (258 % 256 = 2), then add 63 = 65 = 'A', print
        # Use >< to split into Plus(200) and Plus(58) to trigger multi-step overflow
        bf = "+" * 200 + "><" + "+" * 58 + ">" + "+" * 63 + ".<" + "[-]" + ">" + "[-]" + "+" * 10 + "."
        out, rc, timeout = run_bf_code(bf, timeout=5)
        assert not timeout, "Overflow wrapping test timed out"
        assert rc == 0, f"Exited with code {rc}"

    def test_basic_arithmetic(self):
        """Basic: 8*8+1 = 65 = 'A'."""
        bf = "++++++++[->++++++++<]>+.[-]++++++++++."
        out, rc, timeout = run_bf_code(bf, timeout=5)
        assert not timeout, "basic arithmetic timed out"
        assert out == b"A\n", f"Wrong output: {out!r}"


# =========================================================================
# Optimization tests — the compiler must optimize common loop patterns
# =========================================================================

class TestLoopOptimization:
    def test_zero_loop_produces_correct_output(self):
        """Program using [-] pattern should produce correct output."""
        out, rc, timeout = run_bf("clear_loop.b")
        assert not timeout, "clear_loop.b timed out"
        assert rc == 0
        assert out == b"A\n", f"Wrong output: {out!r}"

    def test_zero_loop_optimized(self):
        """Compiler must replace [-] with a single instruction."""
        lines = dump_instructions("+++++[-]+++.")
        op_names = [line.split(": ")[1].split()[0] for line in lines if ": " in line]
        for i in range(len(op_names) - 2):
            if (op_names[i] == "JumpIfZero" and
                op_names[i+1] == "Minus" and
                op_names[i+2] == "JumpIfNotZero"):
                assert False, (
                    "Found unoptimized [-] pattern (JumpIfZero, Minus, JumpIfNotZero). "
                    "The compiler should replace this with a specialized instruction."
                )

    def test_increment_zero_loop_optimized(self):
        """Compiler must also optimize [+] (wraps to 0 on 8-bit cells)."""
        lines = dump_instructions("+++++[+]+++.")
        op_names = [line.split(": ")[1].split()[0] for line in lines if ": " in line]
        for i in range(len(op_names) - 2):
            if (op_names[i] == "JumpIfZero" and
                op_names[i+1] == "Plus" and
                op_names[i+2] == "JumpIfNotZero"):
                assert False, (
                    "Found unoptimized [+] pattern. "
                    "The compiler should replace this with a specialized instruction."
                )

    def test_multiply_pattern_correct_output(self):
        """Program using [->+++<] pattern should produce correct output."""
        out, rc, timeout = run_bf("multiply_loop.b")
        assert not timeout, "multiply_loop.b timed out"
        assert rc == 0
        assert out == b"A\n", f"Wrong output: {out!r}"

    def test_multiply_pattern_optimized(self):
        """Compiler must replace [->+++<] with a single instruction."""
        lines = dump_instructions("+++++++[->+++<].")
        op_names = [line.split(": ")[1].split()[0] for line in lines if ": " in line]
        has_jump_pair = False
        for i in range(len(op_names) - 1):
            if op_names[i] == "JumpIfZero" and "JumpIfNotZero" in op_names[i+1:]:
                has_jump_pair = True
                break
        assert not has_jump_pair, (
            "Found unoptimized multiply loop (JumpIfZero ... JumpIfNotZero). "
            "The compiler should replace this with a specialized instruction."
        )

    def test_multi_target_multiply(self):
        """Multiply to multiple targets: [->++>+++<<]."""
        # cell0=5, [->++>+++<<] → cell1=10, cell2=15
        bf = "+++++[->++>+++<<]>."  # print cell1 = 10 = newline
        out, rc, timeout = run_bf_code(bf, timeout=5)
        assert not timeout, "multi-target multiply timed out"
        assert out == b"\n", f"Wrong output for multi-target multiply: {out!r}"

    def test_scan_right_correct_output(self):
        """Program using [>] scan pattern should produce correct output."""
        bf = "+>+>+>>" + "+" * 65 + "<<<<[>]>.[-]" + "+" * 10 + "."
        out, rc, timeout = run_bf_code(bf, timeout=10)
        assert not timeout, "scan loop test timed out"
        assert rc == 0, f"scan loop exited with code {rc}"
        assert out == b"A\n", f"Wrong output: {out!r}"

    def test_scan_right_optimized(self):
        """Compiler must replace [>] with a single instruction."""
        lines = dump_instructions("+>+>+>>+<<<<<[>].")
        op_names = [line.split(": ")[1].split()[0] for line in lines if ": " in line]
        for i in range(len(op_names) - 2):
            if (op_names[i] == "JumpIfZero" and
                op_names[i+1] == "Right" and
                op_names[i+2] == "JumpIfNotZero"):
                assert False, (
                    "Found unoptimized [>] pattern. "
                    "The compiler should replace this with a specialized instruction."
                )

    def test_scan_left_optimized(self):
        """Compiler must replace [<] with a single instruction."""
        lines = dump_instructions(">>>>+<+<+<+[<].")
        op_names = [line.split(": ")[1].split()[0] for line in lines if ": " in line]
        for i in range(len(op_names) - 2):
            if (op_names[i] == "JumpIfZero" and
                op_names[i+1] == "Left" and
                op_names[i+2] == "JumpIfNotZero"):
                assert False, (
                    "Found unoptimized [<] pattern. "
                    "The compiler should replace this with a specialized instruction."
                )


# =========================================================================
# Performance test
# =========================================================================

class TestPerformance:
    def test_mandelbrot_performance(self):
        """mandelbrot.b must complete within 20 seconds with optimizations."""
        start = time.time()
        out, rc, timeout = run_bf("mandelbrot.b", timeout=20)
        elapsed = time.time() - start
        assert not timeout, (
            f"mandelbrot.b timed out after 20 seconds. "
            f"Compiler optimizations are likely missing or insufficient."
        )
        assert rc == 0, f"mandelbrot.b exited with code {rc}"
        assert len(out) > 1000, (
            f"mandelbrot.b output too short ({len(out)} bytes), expected fractal output"
        )
        # The mandelbrot.b program outputs ASCII art using uppercase letters
        # (A-Z represent escape-time values) and spaces
        has_letters = any(c in out for c in [b"A", b"B", b"C", b"D"])
        assert has_letters, (
            f"mandelbrot.b output doesn't contain expected uppercase letter characters. "
            f"First 100 bytes: {out[:100]!r}"
        )
