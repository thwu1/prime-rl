
"""
Tests for the BPF analysis pipeline:
  /app/bpf_extract - ELF bytecode extraction
  /app/bpf_analyze - static control-flow analysis
  /app/bpf_run     - bytecode execution
"""

import json
import os
import struct
import subprocess
import tempfile
import pytest
import random

MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1
PROGRAMS_DIR = '/app/programs'

COMPILED_EXPECTED_R0 = {
    'simple': 42,
    'arith': 20042,
    'branch': 125,
    'loop': 55,
    'bitmanip': 65184,
}

# ---------------------------------------------------------------------------
# BPF instruction encoder (reference, for constructing test programs)
# ---------------------------------------------------------------------------

def encode_insn(opcode, dst=0, src=0, off=0, imm=0):
    regs = ((src & 0xf) << 4) | (dst & 0xf)
    return struct.pack('<BBhi', opcode, regs, off, imm)

def encode_imm64(dst, val):
    lo = val & 0xFFFFFFFF
    hi = (val >> 32) & 0xFFFFFFFF
    lo_s = lo - 0x100000000 if lo >= 0x80000000 else lo
    hi_s = hi - 0x100000000 if hi >= 0x80000000 else hi
    return encode_insn(0x18, dst, 0, 0, lo_s) + encode_insn(0x00, 0, 0, 0, hi_s)

# ---------------------------------------------------------------------------
# Tool helpers
# ---------------------------------------------------------------------------

def _find_cmd(*names):
    for n in names:
        try:
            subprocess.run([n, '--version'], capture_output=True, check=False)
            return n
        except FileNotFoundError:
            continue
    return None

OBJCOPY = _find_cmd('llvm-objcopy', 'llvm-objcopy-18', 'objcopy')

def run_tool(path, args, timeout=30):
    result = subprocess.run(
        [path] + args,
        capture_output=True, text=True, timeout=timeout
    )
    return result

def reference_extract(elf_path):
    """Extract bytecode using llvm-objcopy, trying common BPF section names."""
    assert OBJCOPY, "No objcopy tool found for reference extraction"
    for section in ['prog', '.text', 'xdp', 'kprobe', 'tracepoint', 'classifier']:
        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as tmp:
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                [OBJCOPY, '--dump-section', f'{section}={tmp_path}', elf_path],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                with open(tmp_path, 'rb') as f:
                    data = f.read()
                if data:
                    return data.hex()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    pytest.fail(f"Could not extract program section from {elf_path}")

# ---------------------------------------------------------------------------
# Hand-crafted test programs with known analysis properties
# ---------------------------------------------------------------------------

# Program: Linear (no branches, no stack)
PROG_LINEAR = (
    encode_insn(0xb7, 1, 0, 0, 42) +    # MOV64_IMM r1, 42
    encode_insn(0xb7, 2, 0, 0, 58) +    # MOV64_IMM r2, 58
    encode_insn(0xbf, 0, 1, 0, 0) +     # MOV64_REG r0, r1
    encode_insn(0x0f, 0, 2, 0, 0) +     # ADD64_REG r0, r2
    encode_insn(0x95)                     # EXIT
)
EXPECT_LINEAR = {
    'instruction_count': 5,
    'basic_blocks': [0],
    'edges': [],
    'has_back_edges': False,
    'max_stack_depth': 0,
    'registers_written': [0, 1, 2],
    'r0': 100,
}

# Program: Branch (conditional, no loops)
# Slots: 0..6
# 0: r1=10  1: r2=20  2: JGT r1,r2,+2(->5)
# 3: r0=r2  4: JA +1(->6)
# 5: r0=r1
# 6: EXIT
PROG_BRANCH = (
    encode_insn(0xb7, 1, 0, 0, 10) +
    encode_insn(0xb7, 2, 0, 0, 20) +
    encode_insn(0x2d, 1, 2, 2, 0) +      # JGT_REG r1, r2, +2
    encode_insn(0xbf, 0, 2, 0, 0) +      # r0 = r2 (fall-through)
    encode_insn(0x05, 0, 0, 1, 0) +      # JA +1
    encode_insn(0xbf, 0, 1, 0, 0) +      # r0 = r1 (branch target)
    encode_insn(0x95)                      # EXIT
)
EXPECT_BRANCH = {
    'instruction_count': 7,
    'basic_blocks': [0, 3, 5, 6],
    'edges': [[0, 3], [0, 5], [3, 6], [5, 6]],
    'has_back_edges': False,
    'max_stack_depth': 0,
    'registers_written': [0, 1, 2],
    'r0': 20,
}

# Program: Loop with back-edge  (sum 1..10)
# Slots: 0..7
# 0: r1=0  1: r2=1  2: r0=0
# 3: r1+=r2  4: r2+=1  5: JLE r2,10,-3(->3)
# 6: r0=r1  7: EXIT
PROG_LOOP = (
    encode_insn(0xb7, 1, 0, 0, 0) +
    encode_insn(0xb7, 2, 0, 0, 1) +
    encode_insn(0xb7, 0, 0, 0, 0) +
    encode_insn(0x0f, 1, 2, 0, 0) +      # ADD64_REG r1, r2
    encode_insn(0x07, 2, 0, 0, 1) +      # ADD64_IMM r2, 1
    encode_insn(0xb5, 2, 0, -3, 10) +    # JLE_IMM r2, 10, -3
    encode_insn(0xbf, 0, 1, 0, 0) +
    encode_insn(0x95)
)
EXPECT_LOOP = {
    'instruction_count': 8,
    'basic_blocks': [0, 3, 6],
    'edges': [[0, 3], [3, 3], [3, 6]],
    'has_back_edges': True,
    'max_stack_depth': 0,
    'registers_written': [0, 1, 2],
    'r0': 55,
}

# Program: Stack operations (store/load via R10)
PROG_STACK = (
    encode_insn(0x7a, 10, 0, -8, 42) +   # ST_DW [r10-8], 42
    encode_insn(0x7a, 10, 0, -16, 58) +  # ST_DW [r10-16], 58
    encode_insn(0x79, 1, 10, -8, 0) +    # LDX_DW r1, [r10-8]
    encode_insn(0x79, 2, 10, -16, 0) +   # LDX_DW r2, [r10-16]
    encode_insn(0xbf, 0, 1, 0, 0) +
    encode_insn(0x0f, 0, 2, 0, 0) +
    encode_insn(0x95)
)
EXPECT_STACK = {
    'instruction_count': 7,
    'basic_blocks': [0],
    'edges': [],
    'has_back_edges': False,
    'max_stack_depth': 16,
    'registers_written': [0, 1, 2],
    'r0': 100,
}

# Program: LD_IMM64 with branching (tests wide instruction counting)
# Slots: 0-1(LD_IMM64) 2(MOV) 3(JGT+2->6) | 4(MOV) 5(JA+1->7) | 6(MOV) | 7(EXIT)
PROG_IMM64 = (
    encode_imm64(1, 0x100000000) +        # LD_IMM64 r1, 4294967296  (slots 0-1)
    encode_insn(0xb7, 2, 0, 0, 1) +      # MOV64_IMM r2, 1          (slot 2)
    encode_insn(0x2d, 1, 2, 2, 0) +      # JGT r1, r2, +2           (slot 3 -> 6)
    encode_insn(0xb7, 0, 0, 0, 0) +      # MOV64_IMM r0, 0          (slot 4)
    encode_insn(0x05, 0, 0, 1, 0) +      # JA +1                    (slot 5 -> 7)
    encode_insn(0xb7, 0, 0, 0, 1) +      # MOV64_IMM r0, 1          (slot 6)
    encode_insn(0x95)                      # EXIT                     (slot 7)
)
EXPECT_IMM64 = {
    'instruction_count': 7,   # LD_IMM64=1 + 5 regular + EXIT = 7
    'basic_blocks': [0, 4, 6, 7],
    'edges': [[0, 4], [0, 6], [4, 7], [6, 7]],
    'has_back_edges': False,
    'max_stack_depth': 0,
    'registers_written': [0, 1, 2],
    'r0': 1,   # 0x100000000 > 1, branch taken, r0=1
}

# Program: Nested loop (two back-edges)
# Outer loop i=0..2, inner loop j=0..2, sum += (i+1)*(j+1)
# sum = 1*1+1*2+1*3 + 2*1+2*2+2*3 + 3*1+3*2+3*3 = 6+12+18 = 36
# Slots:
# 0: r1=0 (sum)   1: r2=0 (i)
# 2: r3=0 (j)                    <-- outer loop start
# 3: r4=r2  4: r4+=1             <-- inner loop start
# 5: r5=r3  6: r5+=1
# 7: r6=r4  8: r6*=r5  9: r1+=r6
# 10: r3+=1  11: JLE r3,2,-9(->3)
# 12: r3=0   13: r2+=1  14: JLE r2,2,-13(->2)
# 15: r0=r1  16: EXIT
PROG_NESTED = (
    encode_insn(0xb7, 1, 0, 0, 0) +      # r1 = 0 (sum)
    encode_insn(0xb7, 2, 0, 0, 0) +      # r2 = 0 (i)
    encode_insn(0xb7, 3, 0, 0, 0) +      # r3 = 0 (j)            [slot 2, outer]
    encode_insn(0xbf, 4, 2, 0, 0) +      # r4 = r2               [slot 3, inner]
    encode_insn(0x07, 4, 0, 0, 1) +      # r4 += 1
    encode_insn(0xbf, 5, 3, 0, 0) +      # r5 = r3
    encode_insn(0x07, 5, 0, 0, 1) +      # r5 += 1
    encode_insn(0xbf, 6, 4, 0, 0) +      # r6 = r4
    encode_insn(0x2f, 6, 5, 0, 0) +      # r6 *= r5   (MUL64_REG)
    encode_insn(0x0f, 1, 6, 0, 0) +      # r1 += r6
    encode_insn(0x07, 3, 0, 0, 1) +      # r3 += 1
    encode_insn(0xb5, 3, 0, -9, 2) +     # JLE r3, 2, -9  -> slot 11-9+1=3
    encode_insn(0xb7, 3, 0, 0, 0) +      # r3 = 0
    encode_insn(0x07, 2, 0, 0, 1) +      # r2 += 1
    encode_insn(0xb5, 2, 0, -13, 2) +    # JLE r2, 2, -13 -> slot 14-13+1=2
    encode_insn(0xbf, 0, 1, 0, 0) +      # r0 = r1
    encode_insn(0x95)                      # EXIT
)
EXPECT_NESTED = {
    'instruction_count': 17,
    'basic_blocks': [0, 2, 3, 12, 15],
    'edges': [[0, 2], [2, 3], [3, 3], [3, 12], [12, 2], [12, 15]],
    'has_back_edges': True,
    'max_stack_depth': 0,
    'registers_written': [0, 1, 2, 3, 4, 5, 6],
    'r0': 36,
}


# =========================================================================
# Tests
# =========================================================================

class TestBPFExtract:
    """Tests for /app/bpf_extract — ELF bytecode extraction."""

    def test_exists(self):
        assert os.path.exists('/app/bpf_extract'), "/app/bpf_extract not found"

    @pytest.mark.parametrize('prog_name', list(COMPILED_EXPECTED_R0.keys()))
    def test_extract_matches_reference(self, prog_name):
        elf_path = os.path.join(PROGRAMS_DIR, f'{prog_name}.o')
        assert os.path.exists(elf_path), f"{elf_path} not found"

        result = run_tool('/app/bpf_extract', [elf_path])
        assert result.returncode == 0, (
            f"bpf_extract failed for {prog_name}: {result.stderr}"
        )
        agent_hex = result.stdout.strip().lower()

        ref_hex = reference_extract(elf_path).lower()
        assert agent_hex == ref_hex, (
            f"Extraction mismatch for {prog_name}.o\n"
            f"Agent({len(agent_hex)}):  {agent_hex[:80]}...\n"
            f"Ref({len(ref_hex)}):    {ref_hex[:80]}..."
        )

    def test_extracted_bytecode_length_multiple_of_8(self):
        for prog_name in COMPILED_EXPECTED_R0:
            elf_path = os.path.join(PROGRAMS_DIR, f'{prog_name}.o')
            result = run_tool('/app/bpf_extract', [elf_path])
            if result.returncode == 0:
                raw = bytes.fromhex(result.stdout.strip())
                assert len(raw) % 8 == 0, (
                    f"{prog_name}: bytecode length {len(raw)} not multiple of 8"
                )


class TestBPFAnalyze:
    """Tests for /app/bpf_analyze — static analysis."""

    def test_exists(self):
        assert os.path.exists('/app/bpf_analyze'), "/app/bpf_analyze not found"

    def _analyze(self, hex_bytecode):
        result = run_tool('/app/bpf_analyze', [hex_bytecode])
        assert result.returncode == 0, f"bpf_analyze failed: {result.stderr}"
        return json.loads(result.stdout)

    def _check_analysis(self, analysis, expected):
        assert analysis['instruction_count'] == expected['instruction_count'], (
            f"instruction_count: got {analysis['instruction_count']}, "
            f"expected {expected['instruction_count']}"
        )
        assert analysis['basic_blocks'] == expected['basic_blocks'], (
            f"basic_blocks: got {analysis['basic_blocks']}, "
            f"expected {expected['basic_blocks']}"
        )
        assert sorted(map(tuple, analysis['edges'])) == sorted(map(tuple, expected['edges'])), (
            f"edges: got {analysis['edges']}, expected {expected['edges']}"
        )
        assert analysis['has_back_edges'] == expected['has_back_edges'], (
            f"has_back_edges: got {analysis['has_back_edges']}, "
            f"expected {expected['has_back_edges']}"
        )
        assert analysis['max_stack_depth'] == expected['max_stack_depth'], (
            f"max_stack_depth: got {analysis['max_stack_depth']}, "
            f"expected {expected['max_stack_depth']}"
        )
        assert sorted(analysis['registers_written']) == expected['registers_written'], (
            f"registers_written: got {analysis['registers_written']}, "
            f"expected {expected['registers_written']}"
        )

    def test_linear_program(self):
        self._check_analysis(self._analyze(PROG_LINEAR.hex()), EXPECT_LINEAR)

    def test_branch_program(self):
        self._check_analysis(self._analyze(PROG_BRANCH.hex()), EXPECT_BRANCH)

    def test_loop_program(self):
        self._check_analysis(self._analyze(PROG_LOOP.hex()), EXPECT_LOOP)

    def test_stack_program(self):
        self._check_analysis(self._analyze(PROG_STACK.hex()), EXPECT_STACK)

    def test_imm64_program(self):
        self._check_analysis(self._analyze(PROG_IMM64.hex()), EXPECT_IMM64)

    def test_nested_loop_program(self):
        self._check_analysis(self._analyze(PROG_NESTED.hex()), EXPECT_NESTED)

    @pytest.mark.parametrize('prog_name', list(COMPILED_EXPECTED_R0.keys()))
    def test_compiled_consistency(self, prog_name):
        """Basic invariants for compiled programs."""
        elf_path = os.path.join(PROGRAMS_DIR, f'{prog_name}.o')
        ref_hex = reference_extract(elf_path)
        analysis = self._analyze(ref_hex)
        assert analysis['instruction_count'] > 0
        assert 0 in analysis['basic_blocks']
        assert 0 in analysis['registers_written'], "R0 must be written"

    def test_compiled_loop_has_back_edges(self):
        ref_hex = reference_extract(os.path.join(PROGRAMS_DIR, 'loop.o'))
        analysis = self._analyze(ref_hex)
        assert analysis['has_back_edges'] is True

    def test_compiled_simple_no_back_edges(self):
        ref_hex = reference_extract(os.path.join(PROGRAMS_DIR, 'simple.o'))
        analysis = self._analyze(ref_hex)
        assert analysis['has_back_edges'] is False

    def test_compiled_arith_has_stack(self):
        """arith.o uses volatile variables, so must have stack depth > 0."""
        ref_hex = reference_extract(os.path.join(PROGRAMS_DIR, 'arith.o'))
        analysis = self._analyze(ref_hex)
        assert analysis['max_stack_depth'] > 0


class TestBPFRun:
    """Tests for /app/bpf_run — bytecode execution."""

    def test_exists(self):
        assert os.path.exists('/app/bpf_run'), "/app/bpf_run not found"

    def _run(self, hex_bytecode):
        result = run_tool('/app/bpf_run', [hex_bytecode])
        assert result.returncode == 0, (
            f"bpf_run failed: rc={result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        return int(result.stdout.strip())

    def test_linear(self):
        assert self._run(PROG_LINEAR.hex()) == EXPECT_LINEAR['r0']

    def test_branch(self):
        assert self._run(PROG_BRANCH.hex()) == EXPECT_BRANCH['r0']

    def test_loop(self):
        assert self._run(PROG_LOOP.hex()) == EXPECT_LOOP['r0']

    def test_stack(self):
        assert self._run(PROG_STACK.hex()) == EXPECT_STACK['r0']

    def test_imm64(self):
        assert self._run(PROG_IMM64.hex()) == EXPECT_IMM64['r0']

    def test_nested_loop(self):
        assert self._run(PROG_NESTED.hex()) == EXPECT_NESTED['r0']

    # ---- Edge cases ----

    def test_div_by_zero_yields_zero(self):
        prog = (
            encode_insn(0xb7, 1, 0, 0, 42) +
            encode_insn(0xb7, 2, 0, 0, 0) +
            encode_insn(0x3f, 1, 2, 0, 0) +    # DIV64 r1, r2
            encode_insn(0xbf, 0, 1, 0, 0) +
            encode_insn(0x95)
        )
        assert self._run(prog.hex()) == 0

    def test_mod_by_zero_64_unchanged(self):
        prog = (
            encode_insn(0xb7, 1, 0, 0, 42) +
            encode_insn(0xb7, 2, 0, 0, 0) +
            encode_insn(0x9f, 1, 2, 0, 0) +    # MOD64 r1, r2
            encode_insn(0xbf, 0, 1, 0, 0) +
            encode_insn(0x95)
        )
        assert self._run(prog.hex()) == 42

    def test_arsh64_negative(self):
        prog = (
            encode_imm64(1, 0x8000000000000000) +
            encode_insn(0xc7, 1, 0, 0, 4) +    # ARSH64 r1, 4
            encode_insn(0xbf, 0, 1, 0, 0) +
            encode_insn(0x95)
        )
        assert self._run(prog.hex()) == 0xF800000000000000

    def test_alu32_zero_extension(self):
        prog = (
            encode_imm64(1, 0xFFFFFFFF00000064) +
            encode_insn(0x04, 1, 0, 0, 0) +    # ADD32 r1, 0
            encode_insn(0xbf, 0, 1, 0, 0) +
            encode_insn(0x95)
        )
        assert self._run(prog.hex()) == 100

    def test_signed_vs_unsigned_branch(self):
        """JGT (unsigned) sees 0xFFFF...FF > 1; JSGT (signed) sees -1 not > 1."""
        prog = (
            encode_insn(0xb7, 1, 0, 0, -1) +
            encode_insn(0xb7, 2, 0, 0, 1) +
            encode_insn(0x2d, 1, 2, 2, 0) +    # JGT unsigned -> taken
            encode_insn(0xb7, 0, 0, 0, 0) +
            encode_insn(0x05, 0, 0, 4, 0) +
            encode_insn(0x6d, 1, 2, 2, 0) +    # JSGT signed -> NOT taken
            encode_insn(0xb7, 0, 0, 0, 42) +
            encode_insn(0x05, 0, 0, 1, 0) +
            encode_insn(0xb7, 0, 0, 0, 99) +
            encode_insn(0x95)
        )
        assert self._run(prog.hex()) == 42

    def test_shift_mask_64(self):
        prog = (
            encode_insn(0xb7, 1, 0, 0, 1) +
            encode_insn(0x67, 1, 0, 0, 65) +   # LSH64 r1, 65 -> masked to 1
            encode_insn(0xbf, 0, 1, 0, 0) +
            encode_insn(0x95)
        )
        assert self._run(prog.hex()) == 2

    def test_arsh32_sign_extend(self):
        """ARSH32 on value with MSB set."""
        prog = (
            encode_imm64(0, 0x1122334485667788) +
            encode_insn(0xc4, 0, 0, 0, 7) +    # ARSH32 r0, 7
            encode_insn(0x95)
        )
        # Lower 32: 0x85667788, ARSH 7 -> 0xFF0ACCEF, zero-extended
        assert self._run(prog.hex()) == 0xFF0ACCEF

    def test_generated_arithmetic(self):
        """Dynamically generated to prevent answer hardcoding."""
        rng = random.Random(42)
        a = rng.randint(1, 1000)
        b = rng.randint(1, 1000)
        c = rng.randint(1, 1000)
        prog = (
            encode_insn(0xb7, 1, 0, 0, a) +
            encode_insn(0xb7, 2, 0, 0, b) +
            encode_insn(0x0f, 1, 2, 0, 0) +
            encode_insn(0x27, 1, 0, 0, c) +
            encode_insn(0xbf, 0, 1, 0, 0) +
            encode_insn(0x95)
        )
        expected = ((a + b) * c) & MASK64
        assert self._run(prog.hex()) == expected

    def test_generated_stack_roundtrip(self):
        """Dynamically generated stack operations."""
        rng = random.Random(123)
        vals = [rng.randint(1, 255) for _ in range(4)]
        prog = b''
        for i, v in enumerate(vals):
            prog += encode_insn(0x7a, 10, 0, -(i + 1) * 8, v)
        prog += encode_insn(0xb7, 0, 0, 0, 0)
        for i in range(4):
            prog += encode_insn(0x79, 1, 10, -(i + 1) * 8, 0)
            prog += encode_insn(0x0f, 0, 1, 0, 0)
        prog += encode_insn(0x95)
        assert self._run(prog.hex()) == sum(vals)


class TestPipeline:
    """Integration: extract -> analyze -> run."""

    @pytest.mark.parametrize('prog_name,expected_r0',
                             list(COMPILED_EXPECTED_R0.items()))
    def test_extract_and_run(self, prog_name, expected_r0):
        elf_path = os.path.join(PROGRAMS_DIR, f'{prog_name}.o')
        ext = run_tool('/app/bpf_extract', [elf_path])
        assert ext.returncode == 0, f"extract failed: {ext.stderr}"
        hex_bc = ext.stdout.strip()

        r = run_tool('/app/bpf_run', [hex_bc])
        assert r.returncode == 0, f"run failed: {r.stderr}"
        assert int(r.stdout.strip()) == expected_r0, (
            f"{prog_name}: R0={r.stdout.strip()}, expected {expected_r0}"
        )

    def test_full_pipeline_loop(self):
        elf_path = os.path.join(PROGRAMS_DIR, 'loop.o')
        ext = run_tool('/app/bpf_extract', [elf_path])
        assert ext.returncode == 0
        hex_bc = ext.stdout.strip()

        ana = run_tool('/app/bpf_analyze', [hex_bc])
        assert ana.returncode == 0
        analysis = json.loads(ana.stdout)
        assert analysis['has_back_edges'] is True
        assert analysis['instruction_count'] > 0
        assert 0 in analysis['basic_blocks']

        r = run_tool('/app/bpf_run', [hex_bc])
        assert r.returncode == 0
        assert int(r.stdout.strip()) == 55

    def test_full_pipeline_bitmanip(self):
        elf_path = os.path.join(PROGRAMS_DIR, 'bitmanip.o')
        ext = run_tool('/app/bpf_extract', [elf_path])
        assert ext.returncode == 0
        hex_bc = ext.stdout.strip()

        ana = run_tool('/app/bpf_analyze', [hex_bc])
        assert ana.returncode == 0
        analysis = json.loads(ana.stdout)
        assert analysis['instruction_count'] > 0
        assert 0 in analysis['registers_written']

        r = run_tool('/app/bpf_run', [hex_bc])
        assert r.returncode == 0
        assert int(r.stdout.strip()) == 65184
