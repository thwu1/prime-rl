"""Tests for BF Multi-Backend Compiler.

"""
import subprocess
import tempfile
import os
import pytest

TAPE_SIZE = 30000


def reference_bf(code, input_data=b""):
    """Reference BF interpreter for verification."""
    code = "".join(c for c in code if c in "><+-.,[]")
    memory = bytearray(TAPE_SIZE)
    ptr = 0
    pc = 0
    output = bytearray()
    input_pos = 0

    jumps = {}
    stack = []
    for i, c in enumerate(code):
        if c == "[":
            stack.append(i)
        elif c == "]":
            if stack:
                j = stack.pop()
                jumps[j] = i
                jumps[i] = j

    while pc < len(code):
        c = code[pc]
        if c == ">":
            ptr = (ptr + 1) % TAPE_SIZE
        elif c == "<":
            ptr = (ptr - 1) % TAPE_SIZE
        elif c == "+":
            memory[ptr] = (memory[ptr] + 1) % 256
        elif c == "-":
            memory[ptr] = (memory[ptr] - 1) % 256
        elif c == ".":
            output.append(memory[ptr])
        elif c == ",":
            if input_pos < len(input_data):
                memory[ptr] = input_data[input_pos]
                input_pos += 1
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


def run_bfc(bf_code, mode, timeout=60):
    """Run bfc.py with given mode on a BF string."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".bf", delete=False) as f:
        f.write(bf_code)
        f.flush()
        fname = f.name
    try:
        result = subprocess.run(
            ["python3", "/app/bfc.py", mode, fname],
            capture_output=True,
            timeout=timeout,
        )
        return result
    finally:
        os.unlink(fname)


def run_bfc_file(path, mode, timeout=60):
    """Run bfc.py with given mode on a file path."""
    result = subprocess.run(
        ["python3", "/app/bfc.py", mode, path],
        capture_output=True,
        timeout=timeout,
    )
    return result


def compile_and_run_c(c_source, timeout=30):
    """Compile C source with gcc and run it, return stdout bytes."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".c", delete=False) as f:
        f.write(c_source)
        f.flush()
        c_path = f.name
    exe_path = c_path.replace(".c", "")
    try:
        comp = subprocess.run(
            ["gcc", "-O2", "-o", exe_path, c_path],
            capture_output=True,
            timeout=timeout,
        )
        if comp.returncode != 0:
            raise RuntimeError(f"gcc failed: {comp.stderr.decode()}")
        run = subprocess.run(
            [exe_path], capture_output=True, timeout=timeout
        )
        return run.stdout
    finally:
        if os.path.exists(c_path):
            os.unlink(c_path)
        if os.path.exists(exe_path):
            os.unlink(exe_path)


def assemble_and_run(asm_source, timeout=30):
    """Assemble x86-64 AT&T source with as, link with gcc, run executable."""
    tmpdir = tempfile.mkdtemp()
    asm_path = os.path.join(tmpdir, "prog.s")
    obj_path = os.path.join(tmpdir, "prog.o")
    exe_path = os.path.join(tmpdir, "prog")
    try:
        with open(asm_path, "w") as f:
            f.write(asm_source)

        asm_result = subprocess.run(
            ["as", "-o", obj_path, asm_path],
            capture_output=True, timeout=timeout,
        )
        if asm_result.returncode != 0:
            raise RuntimeError(
                f"as failed:\nstdout: {asm_result.stdout.decode()}\n"
                f"stderr: {asm_result.stderr.decode()}"
            )

        link_result = subprocess.run(
            ["gcc", "-o", exe_path, obj_path],
            capture_output=True, timeout=timeout,
        )
        if link_result.returncode != 0:
            raise RuntimeError(
                f"gcc link failed:\nstdout: {link_result.stdout.decode()}\n"
                f"stderr: {link_result.stderr.decode()}"
            )

        run_result = subprocess.run(
            [exe_path], capture_output=True, timeout=timeout
        )
        return run_result.stdout
    finally:
        for p in [asm_path, obj_path, exe_path]:
            if os.path.exists(p):
                os.unlink(p)
        if os.path.exists(tmpdir):
            os.rmdir(tmpdir)


def assemble_to_exe(asm_source, timeout=30):
    """Assemble and link, return path to executable (caller must clean up)."""
    tmpdir = tempfile.mkdtemp()
    asm_path = os.path.join(tmpdir, "prog.s")
    obj_path = os.path.join(tmpdir, "prog.o")
    exe_path = os.path.join(tmpdir, "prog")

    with open(asm_path, "w") as f:
        f.write(asm_source)

    subprocess.run(
        ["as", "-o", obj_path, asm_path],
        check=True, capture_output=True, timeout=timeout,
    )
    subprocess.run(
        ["gcc", "-o", exe_path, obj_path],
        check=True, capture_output=True, timeout=timeout,
    )
    return exe_path, tmpdir


def parse_stats(text):
    """Parse stats output into a dict."""
    stats = {}
    for line in text.strip().splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            stats[key.strip()] = int(val.strip())
    return stats


# =====================================================================
# Execution correctness tests
# =====================================================================


class TestExecutionCorrectness:
    """Verify optimized execution produces same output as reference."""

    def test_empty_program(self):
        result = run_bfc("", "run")
        assert result.returncode == 0
        assert result.stdout == b""

    def test_comments_only(self):
        result = run_bfc("this is not BF at all 123", "run")
        assert result.returncode == 0
        assert result.stdout == b""

    def test_hello_world(self):
        bf = open("/app/programs/hello.bf").read()
        expected = reference_bf(bf)
        assert expected == b"Hello World!\n"
        result = run_bfc_file("/app/programs/hello.bf", "run")
        assert result.returncode == 0, f"stderr: {result.stderr.decode()}"
        assert result.stdout == expected

    def test_alphabet(self):
        bf = open("/app/programs/alphabet.bf").read()
        expected = reference_bf(bf)
        assert expected == b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        result = run_bfc_file("/app/programs/alphabet.bf", "run")
        assert result.returncode == 0, f"stderr: {result.stderr.decode()}"
        assert result.stdout == expected

    def test_combined_program(self):
        bf = open("/app/programs/combined.bf").read()
        expected = reference_bf(bf)
        assert expected == b"F"
        result = run_bfc_file("/app/programs/combined.bf", "run")
        assert result.returncode == 0, f"stderr: {result.stderr.decode()}"
        assert result.stdout == expected

    def test_clear_loop_correctness(self):
        bf = "+++++++++++[-]" + "+" * 65 + "."
        expected = reference_bf(bf)
        assert expected == b"A"
        result = run_bfc(bf, "run")
        assert result.returncode == 0
        assert result.stdout == expected

    def test_simple_multiply_loop(self):
        bf = "++++++++[->++++++++<]>+."
        expected = reference_bf(bf)
        assert expected == b"A"
        result = run_bfc(bf, "run")
        assert result.returncode == 0
        assert result.stdout == expected

    def test_multi_target_copy_loop(self):
        bf = "++++++++++[->++++++++>+++++++<<]>.>."
        expected = reference_bf(bf)
        assert expected == b"PF"
        result = run_bfc(bf, "run")
        assert result.returncode == 0
        assert result.stdout == expected

    def test_nested_loops(self):
        bf = "++++[>+++++[>++<-]<-]>>+."
        expected = reference_bf(bf)
        assert expected == b")"
        result = run_bfc(bf, "run")
        assert result.returncode == 0
        assert result.stdout == expected

    def test_copy_loop_with_subtraction_factor(self):
        bf = "+++[->-<]>."
        expected = reference_bf(bf)
        result = run_bfc(bf, "run")
        assert result.returncode == 0
        assert result.stdout == expected

    def test_wrapping_arithmetic(self):
        bf = "-."
        expected = reference_bf(bf)
        assert expected == bytes([255])
        result = run_bfc(bf, "run")
        assert result.returncode == 0
        assert result.stdout == expected


# =====================================================================
# IR optimization verification tests
# =====================================================================


class TestIROptimizations:
    """Verify specific optimizations appear in IR output."""

    def test_contraction_in_ir(self):
        bf = "+++++>>>."
        result = run_bfc(bf, "ir")
        ir = result.stdout.decode()
        assert "ADD_DATA 5" in ir
        assert "ADD_PTR 3" in ir

    def test_mixed_contraction(self):
        bf = "+++--.>><<<."
        result = run_bfc(bf, "ir")
        ir = result.stdout.decode()
        assert "ADD_DATA 1" in ir
        assert "SUB_PTR 1" in ir

    def test_clear_loop_in_ir(self):
        bf = "+++++[-]."
        result = run_bfc(bf, "ir")
        ir = result.stdout.decode()
        assert "SET 0" in ir
        assert "LOOP_START" not in ir

    def test_clear_loop_with_plus(self):
        bf = "+++++[+]."
        result = run_bfc(bf, "ir")
        ir = result.stdout.decode()
        assert "SET 0" in ir

    def test_copy_mul_in_ir(self):
        bf = "+++++[->+++<]."
        result = run_bfc(bf, "ir")
        ir = result.stdout.decode()
        assert "MUL_ADD 1 3" in ir
        assert "SET 0" in ir

    def test_multi_target_copy_mul_in_ir(self):
        bf = "+++++[->>++>+++<<<]."
        result = run_bfc(bf, "ir")
        ir = result.stdout.decode()
        assert "MUL_ADD 2 2" in ir
        assert "MUL_ADD 3 3" in ir
        assert "SET 0" in ir

    def test_scan_right_in_ir(self):
        bf = "+>+>+>+<<< [>>>] ."
        result = run_bfc(bf, "ir")
        ir = result.stdout.decode()
        assert "SCAN_RIGHT 3" in ir

    def test_scan_left_in_ir(self):
        bf = ">>>+>+>+<<<<<+[<<<]."
        result = run_bfc(bf, "ir")
        ir = result.stdout.decode()
        assert "SCAN_LEFT 3" in ir

    def test_set_fold_in_ir(self):
        bf = "+++++[-]+++++."
        result = run_bfc(bf, "ir")
        ir = result.stdout.decode()
        assert "SET 5" in ir

    def test_nested_loop_not_copy_mul(self):
        bf = "+[->+[>+<-]<]."
        result = run_bfc(bf, "ir")
        ir = result.stdout.decode()
        assert "LOOP_START" in ir
        assert "LOOP_END" in ir

    def test_unbalanced_ptr_not_copy_mul(self):
        bf = "+++++[->+]."
        result = run_bfc(bf, "ir")
        ir = result.stdout.decode()
        assert "LOOP_START" in ir

    def test_io_in_loop_not_copy_mul(self):
        bf = "+++++[-.>+<]."
        result = run_bfc(bf, "ir")
        ir = result.stdout.decode()
        assert "LOOP_START" in ir
        assert "MUL_ADD" not in ir


# =====================================================================
# C code generation tests
# =====================================================================


class TestCCodeGeneration:
    """Verify gen-c produces compilable C with correct output."""

    def test_c_hello_world(self):
        bf = open("/app/programs/hello.bf").read()
        expected = reference_bf(bf)
        result = run_bfc_file("/app/programs/hello.bf", "gen-c")
        assert result.returncode == 0, f"gen-c failed: {result.stderr.decode()}"
        c_source = result.stdout.decode()
        assert "main" in c_source
        output = compile_and_run_c(c_source)
        assert output == expected

    def test_c_alphabet(self):
        bf = open("/app/programs/alphabet.bf").read()
        expected = reference_bf(bf)
        result = run_bfc_file("/app/programs/alphabet.bf", "gen-c")
        assert result.returncode == 0
        c_source = result.stdout.decode()
        output = compile_and_run_c(c_source)
        assert output == expected

    def test_c_combined(self):
        bf = open("/app/programs/combined.bf").read()
        expected = reference_bf(bf)
        result = run_bfc_file("/app/programs/combined.bf", "gen-c")
        assert result.returncode == 0
        c_source = result.stdout.decode()
        output = compile_and_run_c(c_source)
        assert output == expected

    def test_c_nested_loops(self):
        bf = "++++[>+++++[>++<-]<-]>>+."
        expected = reference_bf(bf)
        result = run_bfc(bf, "gen-c")
        assert result.returncode == 0
        c_source = result.stdout.decode()
        output = compile_and_run_c(c_source)
        assert output == expected

    def test_c_wrapping(self):
        bf = "-."
        expected = reference_bf(bf)
        result = run_bfc(bf, "gen-c")
        assert result.returncode == 0
        c_source = result.stdout.decode()
        output = compile_and_run_c(c_source)
        assert output == expected


# =====================================================================
# x86-64 assembly code generation tests
# =====================================================================


class TestAsmCodeGeneration:
    """Verify gen-asm produces valid x86-64 assembly with correct output."""

    def test_asm_hello_world(self):
        bf = open("/app/programs/hello.bf").read()
        expected = reference_bf(bf)
        result = run_bfc_file("/app/programs/hello.bf", "gen-asm")
        assert result.returncode == 0, f"gen-asm failed: {result.stderr.decode()}"
        asm_source = result.stdout.decode()
        output = assemble_and_run(asm_source)
        assert output == expected

    def test_asm_alphabet(self):
        bf = open("/app/programs/alphabet.bf").read()
        expected = reference_bf(bf)
        result = run_bfc_file("/app/programs/alphabet.bf", "gen-asm")
        assert result.returncode == 0
        asm_source = result.stdout.decode()
        output = assemble_and_run(asm_source)
        assert output == expected

    def test_asm_combined(self):
        bf = open("/app/programs/combined.bf").read()
        expected = reference_bf(bf)
        result = run_bfc_file("/app/programs/combined.bf", "gen-asm")
        assert result.returncode == 0
        asm_source = result.stdout.decode()
        output = assemble_and_run(asm_source)
        assert output == expected

    def test_asm_nested_loops(self):
        bf = "++++[>+++++[>++<-]<-]>>+."
        expected = reference_bf(bf)
        result = run_bfc(bf, "gen-asm")
        assert result.returncode == 0
        asm_source = result.stdout.decode()
        output = assemble_and_run(asm_source)
        assert output == expected

    def test_asm_wrapping(self):
        bf = "-."
        expected = reference_bf(bf)
        result = run_bfc(bf, "gen-asm")
        assert result.returncode == 0
        asm_source = result.stdout.decode()
        output = assemble_and_run(asm_source)
        assert output == expected

    def test_asm_empty_program(self):
        result = run_bfc("", "gen-asm")
        assert result.returncode == 0
        asm_source = result.stdout.decode()
        output = assemble_and_run(asm_source)
        assert output == b""

    def test_asm_mul_add_correctness(self):
        """Assembly MUL_ADD must produce correct values for multi-target copy."""
        bf = "++++++++++[->++++++++>+++++++<<]>.>."
        expected = reference_bf(bf)
        assert expected == b"PF"
        result = run_bfc(bf, "gen-asm")
        assert result.returncode == 0
        asm_source = result.stdout.decode()
        output = assemble_and_run(asm_source)
        assert output == expected

    def test_asm_valid_elf(self):
        """Assembled output must be a valid x86-64 ELF per readelf."""
        bf = open("/app/programs/hello.bf").read()
        result = run_bfc_file("/app/programs/hello.bf", "gen-asm")
        assert result.returncode == 0
        asm_source = result.stdout.decode()
        exe_path, tmpdir = assemble_to_exe(asm_source)
        try:
            readelf = subprocess.run(
                ["readelf", "-h", exe_path],
                capture_output=True, timeout=10,
            )
            assert readelf.returncode == 0
            hdr = readelf.stdout.decode()
            assert "ELF" in hdr
            assert "x86-64" in hdr.lower() or "x86_64" in hdr.lower()
        finally:
            for p in [exe_path, exe_path + ".o",
                       os.path.join(tmpdir, "prog.s"),
                       os.path.join(tmpdir, "prog.o")]:
                if os.path.exists(p):
                    os.unlink(p)
            if os.path.exists(tmpdir):
                os.rmdir(tmpdir)

    def test_asm_objdump_disassembly(self):
        """Compiled assembly can be disassembled and contains main."""
        bf = "+++++[-]" + "+" * 65 + "."
        result = run_bfc(bf, "gen-asm")
        assert result.returncode == 0
        asm_source = result.stdout.decode()
        exe_path, tmpdir = assemble_to_exe(asm_source)
        try:
            objdump = subprocess.run(
                ["objdump", "-d", exe_path],
                capture_output=True, timeout=10,
            )
            assert objdump.returncode == 0
            disasm = objdump.stdout.decode()
            assert "main" in disasm
            assert "putchar" in disasm
        finally:
            for p in [exe_path,
                       os.path.join(tmpdir, "prog.s"),
                       os.path.join(tmpdir, "prog.o")]:
                if os.path.exists(p):
                    os.unlink(p)
            if os.path.exists(tmpdir):
                os.rmdir(tmpdir)


# =====================================================================
# Stats tests
# =====================================================================


class TestStats:
    """Verify stats output reports correct optimization counts."""

    def test_stats_keys_present(self):
        bf = "+++++[-]."
        result = run_bfc(bf, "stats")
        assert result.returncode == 0
        stats = parse_stats(result.stdout.decode())
        for key in ["contraction", "clear_loop", "copy_mul_loop", "scan_loop", "set_fold"]:
            assert key in stats, f"Missing stats key: {key}"

    def test_stats_clear_loop(self):
        bf = "+++++[-]."
        result = run_bfc(bf, "stats")
        stats = parse_stats(result.stdout.decode())
        assert stats["clear_loop"] >= 1

    def test_stats_copy_mul(self):
        bf = "+++++[->+++<]."
        result = run_bfc(bf, "stats")
        stats = parse_stats(result.stdout.decode())
        assert stats["copy_mul_loop"] >= 1

    def test_stats_scan(self):
        bf = "+[>>>]."
        result = run_bfc(bf, "stats")
        stats = parse_stats(result.stdout.decode())
        assert stats["scan_loop"] >= 1

    def test_stats_contraction(self):
        bf = "+++++>>>."
        result = run_bfc(bf, "stats")
        stats = parse_stats(result.stdout.decode())
        assert stats["contraction"] >= 1

    def test_stats_set_fold(self):
        bf = "+++++[-]+++++."
        result = run_bfc(bf, "stats")
        stats = parse_stats(result.stdout.decode())
        assert stats["set_fold"] >= 1

    def test_stats_combined(self):
        bf = open("/app/programs/combined.bf").read()
        result = run_bfc_file("/app/programs/combined.bf", "stats")
        assert result.returncode == 0
        stats = parse_stats(result.stdout.decode())
        assert stats["clear_loop"] >= 1
        assert stats["copy_mul_loop"] >= 2
        assert stats["scan_loop"] >= 1
        assert stats["set_fold"] >= 1
