#!/usr/bin/env python3
"""Tests for the optimizing BF compiler with bytecode VM and x86-64 NASM backend."""

import subprocess
import json
import os
import tempfile
import stat
import pytest

BFCOMP = "/app/bfcomp.py"


def bf_reference(code, input_bytes=b"", max_steps=50_000_000):
    """Simple reference BF interpreter for correctness checking."""
    code = "".join(c for c in code if c in "><+-.,[]")
    jumps = {}
    stack = []
    for i, c in enumerate(code):
        if c == "[":
            stack.append(i)
        elif c == "]":
            j = stack.pop()
            jumps[j] = i
            jumps[i] = j
    memory = bytearray(30000)
    ptr = 0
    pc = 0
    ip = 0
    output = bytearray()
    steps = 0
    while pc < len(code):
        steps += 1
        if steps > max_steps:
            raise RuntimeError("Max steps exceeded")
        c = code[pc]
        if c == ">":
            ptr = (ptr + 1) % 30000
        elif c == "<":
            ptr = (ptr - 1) % 30000
        elif c == "+":
            memory[ptr] = (memory[ptr] + 1) & 0xFF
        elif c == "-":
            memory[ptr] = (memory[ptr] - 1) & 0xFF
        elif c == ".":
            output.append(memory[ptr])
        elif c == ",":
            if ip < len(input_bytes):
                memory[ptr] = input_bytes[ip]
                ip += 1
            else:
                memory[ptr] = 0
        elif c == "[":
            if memory[ptr] == 0:
                pc = jumps[pc]
        elif c == "]":
            if memory[ptr] != 0:
                pc = jumps[pc]
        pc += 1
    return bytes(output)


def run_bfcomp(subcommand, code, input_bytes=b"", timeout=60, extra_args=None):
    """Run bfcomp.py with the given subcommand on BF code."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".bf", delete=False) as f:
        f.write(code)
        tmp = f.name
    try:
        cmd = ["python3", BFCOMP, subcommand, tmp]
        if extra_args:
            cmd.extend(extra_args)
        result = subprocess.run(
            cmd, capture_output=True, timeout=timeout, input=input_bytes
        )
        return result
    finally:
        os.unlink(tmp)


def build_and_run_native(code, input_bytes=b"", timeout=60):
    """Build a native executable from BF code and run it."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".bf", delete=False) as f:
        f.write(code)
        bf_path = f.name
    out_path = bf_path + "_bin"
    try:
        build_result = subprocess.run(
            ["python3", BFCOMP, "build", bf_path, out_path],
            capture_output=True, timeout=timeout
        )
        if build_result.returncode != 0:
            raise RuntimeError(
                f"Build failed: {build_result.stderr.decode()}\n"
                f"stdout: {build_result.stdout.decode()}"
            )
        os.chmod(out_path, stat.S_IRWXU)
        run_result = subprocess.run(
            [out_path], capture_output=True, timeout=timeout, input=input_bytes
        )
        return run_result
    finally:
        for p in [bf_path, out_path]:
            if os.path.exists(p):
                os.unlink(p)


def get_asm_source(code, timeout=60):
    """Generate NASM assembly source from BF code and return it as a string."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".bf", delete=False) as f:
        f.write(code)
        bf_path = f.name
    asm_path = bf_path + ".asm"
    try:
        result = subprocess.run(
            ["python3", BFCOMP, "asm", bf_path, asm_path],
            capture_output=True, timeout=timeout
        )
        assert result.returncode == 0, f"asm failed: {result.stderr.decode()}"
        with open(asm_path) as af:
            return af.read()
    finally:
        for p in [bf_path, asm_path]:
            if os.path.exists(p):
                os.unlink(p)


# ======= BYTECODE VM CORRECTNESS TESTS =======


class TestCorrectness:
    """Test that the bytecode VM produces correct output for various BF programs."""

    def test_empty_program(self):
        result = run_bfcomp("run", "")
        assert result.returncode == 0
        assert result.stdout == b""

    def test_comment_only(self):
        result = run_bfcomp("run", "this is just a comment with no bf ops")
        assert result.returncode == 0
        assert result.stdout == b""

    def test_hello_world(self):
        code = (
            "++++++++[>++++[>++>+++>+++>+<<<<-]>+>+>->>+[<]<-]>>"
            ".>---.+++++++..+++.>>.<-.<.+++.------.--------.>>+.>++."
        )
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_alphabet(self):
        code = "++++++++[>++++++++<-]>+>++++[>++++++<-]>++[<<.+>>-]"
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_simple_add(self):
        code = "+++>+++++[-<+>]<>++++++[<++++++++>-]<."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_nested_loops(self):
        code = "+++++[>+++[>++<-]<-]>>."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_wrapping_overflow(self):
        code = "+" * 256 + "."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_wrapping_underflow(self):
        code = "-."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_clear_loop_correctness(self):
        code = "++++++++++[-]+++++[>+++++++++++++<-]>."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_copy_loop_correctness(self):
        code = "+++++[>+++++++++++++<-]>[->+<]>."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_multiply_loop_correctness(self):
        code = "+++++[->>+++<<]>>."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_multiply_loop_end_dec(self):
        """Multiply loop with decrement at end: [>+++<-]"""
        code = "+++++[>+++<-]>."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_scan_loop_correctness(self):
        code = "+>+>+>+>+>>++++++++[>++++++++<-]>+<<<<<<<[>]>>."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_multi_target_multiply_correctness(self):
        code = "+++[->>++>+++<<<]>>."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_negative_offset_multiply_correctness(self):
        code = ">+++++[-<+++>]<."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_dead_code_correctness(self):
        code = "+++++[-][>+++<]++++++++[>++++++++<-]>+."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_consecutive_clear_loops(self):
        code = "+++++[-][-][-]++++++++[>++++++++<-]>+."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_digits_zero_to_nine(self):
        code = "++++++[>++++++++<-]>>++++++++++[<<.+>>-]"
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_deep_nested_loops(self):
        code = "+++[>+++++[>++<-]<-]>>."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected


# ======= NATIVE EXECUTION TESTS =======


class TestNativeExecution:
    """Test that the NASM backend produces correct native executables."""

    def test_native_hello_world(self):
        code = (
            "++++++++[>++++[>++>+++>+++>+<<<<-]>+>+>->>+[<]<-]>>"
            ".>---.+++++++..+++.>>.<-.<.+++.------.--------.>>+.>++."
        )
        expected = bf_reference(code)
        result = build_and_run_native(code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_native_alphabet(self):
        code = "++++++++[>++++++++<-]>+>++++[>++++++<-]>++[<<.+>>-]"
        expected = bf_reference(code)
        result = build_and_run_native(code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_native_nested_loops(self):
        code = "+++++[>+++[>++<-]<-]>>."
        expected = bf_reference(code)
        result = build_and_run_native(code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_native_clear_loop(self):
        code = "++++++++++[-]+++++[>+++++++++++++<-]>."
        expected = bf_reference(code)
        result = build_and_run_native(code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_native_multiply_loop(self):
        code = "+++++[->>+++<<]>>."
        expected = bf_reference(code)
        result = build_and_run_native(code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_native_multiply_loop_end_dec(self):
        """Multiply loop with decrement at end: [>+++<-]"""
        code = "+++++[>+++<-]>."
        expected = bf_reference(code)
        result = build_and_run_native(code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_native_negative_offset_multiply(self):
        code = ">+++++[-<+++>]<."
        expected = bf_reference(code)
        result = build_and_run_native(code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_native_scan_loop(self):
        code = "+>+>+>+>+>>++++++++[>++++++++<-]>+<<<<<<<[>]>>."
        expected = bf_reference(code)
        result = build_and_run_native(code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_native_wrapping(self):
        code = "-."
        expected = bf_reference(code)
        result = build_and_run_native(code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_native_digits(self):
        code = "++++++[>++++++++<-]>>++++++++++[<<.+>>-]"
        expected = bf_reference(code)
        result = build_and_run_native(code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_native_dead_code(self):
        code = "+++++[-][>+++<]++++++++[>++++++++<-]>+."
        expected = bf_reference(code)
        result = build_and_run_native(code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_native_multi_target_multiply(self):
        code = "+++[->>++>+++<<<]>>."
        expected = bf_reference(code)
        result = build_and_run_native(code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_native_matches_bytecode(self):
        """A complex program produces identical output via both backends."""
        code = (
            "++++++++[>++++[>++>+++>+++>+<<<<-]>+>+>->>+[<]<-]>>"
            ".>---.+++++++..+++.>>.<-.<.+++.------.--------.>>+.>++."
        )
        vm_result = run_bfcomp("run", code)
        native_result = build_and_run_native(code)
        assert vm_result.returncode == 0
        assert native_result.returncode == 0
        assert vm_result.stdout == native_result.stdout


# ======= ASSEMBLY PATTERN TESTS =======


class TestAssemblyPatterns:
    """Verify that the generated NASM assembly uses correct patterns."""

    def test_asm_clear_loop_uses_mov_zero(self):
        """SET_ZERO should emit 'mov byte [r13], 0', not a loop."""
        asm = get_asm_source("+++++[-].")
        assert "mov byte [r13], 0" in asm

    def test_asm_clear_loop_plus_also_optimized(self):
        """[+] should also be recognized as a clear loop."""
        asm = get_asm_source("+++++[+].")
        assert "mov byte [r13], 0" in asm

    def test_asm_contraction_uses_count(self):
        """+++++ should generate 'add byte [r13], 5', not five add 1s."""
        asm = get_asm_source("+++++.")
        assert "add byte [r13], 5" in asm

    def test_asm_dec_ptr_uses_sub(self):
        """<<< should generate 'sub r13, 3', not 'add r13, 3'."""
        asm = get_asm_source("<<<")
        assert "sub r13, 3" in asm

    def test_asm_write_uses_r13_as_buf(self):
        """WRITE_STDOUT must use r13 as the buffer pointer (mov rsi, r13)."""
        asm = get_asm_source(".")
        assert "mov rsi, r13" in asm

    def test_asm_multiply_uses_imul(self):
        """MUL_COPY should use imul for the multiply operation."""
        asm = get_asm_source("[->>+++<<]")
        assert "imul" in asm

    def test_asm_multiply_adds_to_target(self):
        """MUL_COPY should add the product to the target cell."""
        asm = get_asm_source("[->>+++<<]")
        assert "add byte [r13 + 2], al" in asm

    def test_asm_scan_has_loop(self):
        """SCAN should generate a compare-jump loop, not a nop."""
        asm = get_asm_source("[>]")
        assert "SCAN stub" not in asm
        assert "cmp byte [r13], 0" in asm
        assert "add r13, 1" in asm

    def test_asm_negative_offset_multiply(self):
        """MUL_COPY with negative offset should use [r13 - N] addressing."""
        asm = get_asm_source("[-<+++>]")
        assert "add byte [r13 - 1], al" in asm

    def test_asm_generates_valid_elf(self):
        """The build command must produce a valid ELF64 binary recognizable by objdump."""
        code = "++++++++[>++++++++<-]>+."
        with tempfile.NamedTemporaryFile(mode="w", suffix=".bf", delete=False) as f:
            f.write(code)
            bf_path = f.name
        out_path = bf_path + "_bin"
        try:
            subprocess.run(
                ["python3", BFCOMP, "build", bf_path, out_path],
                check=True, capture_output=True, timeout=60
            )
            result = subprocess.run(
                ["objdump", "-f", out_path],
                capture_output=True, timeout=30
            )
            assert result.returncode == 0
            output = result.stdout.decode()
            assert "elf64-x86-64" in output
        finally:
            for p in [bf_path, out_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_asm_objdump_disassembly_has_syscall(self):
        """Generated binary must contain syscall instructions visible in objdump -d."""
        code = "++++++++[>++++++++<-]>+."
        with tempfile.NamedTemporaryFile(mode="w", suffix=".bf", delete=False) as f:
            f.write(code)
            bf_path = f.name
        out_path = bf_path + "_bin"
        try:
            subprocess.run(
                ["python3", BFCOMP, "build", bf_path, out_path],
                check=True, capture_output=True, timeout=60
            )
            result = subprocess.run(
                ["objdump", "-d", out_path],
                capture_output=True, timeout=30
            )
            assert result.returncode == 0
            disasm = result.stdout.decode()
            assert "syscall" in disasm
        finally:
            for p in [bf_path, out_path]:
                if os.path.exists(p):
                    os.unlink(p)


# ======= BYTECODE OPTIMIZATION TESTS =======


class TestBytecodeOptimizations:
    """Test that specific optimizations are applied to the bytecode."""

    def _get_bytecode(self, code):
        result = run_bfcomp("bytecode", code)
        assert result.returncode == 0, f"bytecode failed: {result.stderr.decode()}"
        return result.stdout.decode().strip()

    def test_contraction(self):
        bc = self._get_bytecode("++++++")
        lines = [l for l in bc.split("\n") if l.strip()]
        assert len(lines) <= 2
        assert any("INC_DATA 6" in l for l in lines)

    def test_ptr_contraction(self):
        bc = self._get_bytecode(">>>>>")
        lines = [l for l in bc.split("\n") if l.strip()]
        assert any("INC_PTR 5" in l for l in lines)

    def test_clear_loop_minus(self):
        bc = self._get_bytecode("+++++[-]")
        assert "SET_ZERO" in bc

    def test_clear_loop_plus(self):
        bc = self._get_bytecode("+++++[+]")
        assert "SET_ZERO" in bc

    def test_simple_copy_detected(self):
        bc = self._get_bytecode("[->+<]")
        assert "MUL_COPY" in bc

    def test_multiply_loop_detected(self):
        bc = self._get_bytecode("[->>+++<<]")
        assert "MUL_COPY 2 3" in bc

    def test_multiply_loop_end_dec_detected(self):
        """Detect multiply loops where decrement is at end: [>+++<-]"""
        bc = self._get_bytecode("[>+++<-]")
        assert "MUL_COPY" in bc

    def test_multi_target_multiply(self):
        bc = self._get_bytecode("[->>+++>++<<<]")
        mul_copy_count = bc.count("MUL_COPY")
        assert mul_copy_count >= 2

    def test_negative_offset_copy(self):
        bc = self._get_bytecode("[-<+>]")
        assert "MUL_COPY -1 1" in bc

    def test_scan_right_detected(self):
        bc = self._get_bytecode("[>]")
        assert "SCAN" in bc

    def test_scan_left_detected(self):
        bc = self._get_bytecode("[<]")
        assert "SCAN" in bc

    def test_scan_step_detected(self):
        bc = self._get_bytecode("[>>>]")
        assert "SCAN 3" in bc

    def test_dead_code_eliminated(self):
        bc = self._get_bytecode("[-][+++>.<-]")
        assert "WRITE_STDOUT" not in bc

    def test_cancellation(self):
        bc = self._get_bytecode("+++---")
        lines = [l for l in bc.split("\n") if l.strip()]
        assert not any("INC_DATA" in l for l in lines)
        assert not any("DEC_DATA" in l for l in lines)

    def test_partial_cancellation(self):
        bc = self._get_bytecode("+++++---")
        lines = [l for l in bc.split("\n") if l.strip()]
        assert any("INC_DATA 2" in l for l in lines)

    def test_ptr_cancellation(self):
        bc = self._get_bytecode(">>><<<")
        lines = [l for l in bc.split("\n") if l.strip()]
        assert not any("INC_PTR" in l for l in lines)
        assert not any("DEC_PTR" in l for l in lines)

    def test_multiply_loop_has_set_zero(self):
        bc = self._get_bytecode("[->>+++<<]")
        assert "SET_ZERO" in bc


# ======= STATS TESTS =======


class TestStats:
    """Test that optimization statistics are correctly reported."""

    def _get_stats(self, code):
        result = run_bfcomp("stats", code)
        assert result.returncode == 0, f"stats failed: {result.stderr.decode()}"
        return json.loads(result.stdout.decode())

    def test_stats_schema(self):
        stats = self._get_stats("+++.")
        assert isinstance(stats["source_length"], int)
        assert isinstance(stats["bytecode_length"], int)
        assert isinstance(stats["optimizations"], dict)
        opts = stats["optimizations"]
        for key in [
            "contractions",
            "cancellations",
            "clear_loops",
            "multiply_loops",
            "scan_loops",
            "dead_code_eliminated",
        ]:
            assert key in opts, f"Missing key: {key}"
            assert isinstance(opts[key], int), f"{key} must be int"

    def test_source_length(self):
        code = "+++[->+<].hello world"
        stats = self._get_stats(code)
        bf_chars = sum(1 for c in code if c in "><+-.,[]")
        assert stats["source_length"] == bf_chars

    def test_clear_loop_count(self):
        stats = self._get_stats("+++[-]+++[-]+++[-]")
        assert stats["optimizations"]["clear_loops"] == 3

    def test_multiply_loop_count(self):
        stats = self._get_stats("[->>+++<<][-<++>]")
        assert stats["optimizations"]["multiply_loops"] == 2

    def test_scan_loop_count(self):
        stats = self._get_stats("[>][<][>>>]")
        assert stats["optimizations"]["scan_loops"] == 3

    def test_dead_code_count(self):
        stats = self._get_stats("[-][+++][-][---]")
        assert stats["optimizations"]["dead_code_eliminated"] == 2

    def test_contraction_count(self):
        stats = self._get_stats("+++++>>>")
        assert stats["optimizations"]["contractions"] >= 2

    def test_bytecode_shorter_than_source(self):
        code = (
            "++++++++[>++++[>++>+++>+++>+<<<<-]>+>+>->>+[<]<-]>>"
            ".>---.+++++++..+++.>>.<-.<.+++.------.--------.>>+.>++."
        )
        stats = self._get_stats(code)
        assert stats["bytecode_length"] < stats["source_length"]


# ======= EDGE CASE TESTS =======


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_file_from_disk(self):
        bf_file = "/app/programs/hello.bf"
        if os.path.exists(bf_file):
            result = subprocess.run(
                ["python3", BFCOMP, "run", bf_file],
                capture_output=True, timeout=30, input=b""
            )
            assert result.returncode == 0
            expected = b"Hello World!\n"
            assert result.stdout == expected

    def test_only_increments(self):
        code = "+" * 100 + "."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_pointer_movement_only(self):
        code = ">>><<<>>>."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_nested_loops_deep(self):
        code = "+++[>+++++[>++<-]<-]>>."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_single_dot(self):
        result = run_bfcomp("run", ".")
        assert result.returncode == 0
        assert result.stdout == b"\x00"

    def test_subtract_below_zero(self):
        code = "--."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected

    def test_all_subcommands_exist(self):
        code = "+++."
        for cmd in ["run", "bytecode", "stats"]:
            result = run_bfcomp(cmd, code)
            assert result.returncode == 0, f"Subcommand '{cmd}' failed"

    def test_asm_subcommand_exists(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".bf", delete=False) as f:
            f.write("+++.")
            bf_path = f.name
        asm_path = bf_path + ".asm"
        try:
            result = subprocess.run(
                ["python3", BFCOMP, "asm", bf_path, asm_path],
                capture_output=True, timeout=30
            )
            assert result.returncode == 0
            assert os.path.exists(asm_path)
        finally:
            for p in [bf_path, asm_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_build_subcommand_exists(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".bf", delete=False) as f:
            f.write("+++.")
            bf_path = f.name
        out_path = bf_path + "_bin"
        try:
            result = subprocess.run(
                ["python3", BFCOMP, "build", bf_path, out_path],
                capture_output=True, timeout=60
            )
            assert result.returncode == 0
            assert os.path.exists(out_path)
        finally:
            for p in [bf_path, out_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_large_contraction(self):
        """A long sequence of identical ops should contract to one instruction."""
        code = "+" * 200 + "."
        expected = bf_reference(code)
        result = run_bfcomp("run", code)
        assert result.returncode == 0
        assert result.stdout == expected
        bc = run_bfcomp("bytecode", code).stdout.decode().strip()
        lines = [l for l in bc.split("\n") if l.strip()]
        assert any("INC_DATA 200" in l for l in lines)

    def test_native_empty_program(self):
        """An empty BF program should produce a valid binary that exits cleanly."""
        result = build_and_run_native("")
        assert result.returncode == 0
        assert result.stdout == b""
