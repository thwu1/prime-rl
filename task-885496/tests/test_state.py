
import pytest
import sys

sys.path.insert(0, '/app')


# === Known binary encodings from the original Verilog test programs ===

MATADD_PROGRAM = [
    0x50DE, 0x300F, 0x9100, 0x9208, 0x9310,
    0x3410, 0x7440, 0x3520, 0x7550, 0x3645,
    0x3730, 0x8076, 0xF000
]

MATMUL_PROGRAM = [
    0x50DE, 0x300F, 0x9101, 0x9202, 0x9300,
    0x9404, 0x9508, 0x6602, 0x5762, 0x4707,
    0x9800, 0x9900,
    0x5A62, 0x3AA9, 0x3AA3, 0x7AA0,
    0x5B92, 0x3BB7, 0x3BB4, 0x7BB0,
    0x5CAB, 0x388C, 0x3991, 0x2092, 0x180C,
    0x3950, 0x8098, 0xF000
]

MATADD_ASM = """
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx
CONST R1, #0
CONST R2, #8
CONST R3, #16
ADD R4, R1, R0
LDR R4, R4
ADD R5, R2, R0
LDR R5, R5
ADD R6, R4, R5
ADD R7, R3, R0
STR R7, R6
RET
"""

MATMUL_ASM = """
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx
CONST R1, #1
CONST R2, #2
CONST R3, #0
CONST R4, #4
CONST R5, #8
DIV R6, R0, R2
MUL R7, R6, R2
SUB R7, R0, R7
CONST R8, #0
CONST R9, #0
LOOP:
  MUL R10, R6, R2
  ADD R10, R10, R9
  ADD R10, R10, R3
  LDR R10, R10
  MUL R11, R9, R2
  ADD R11, R11, R7
  ADD R11, R11, R4
  LDR R11, R11
  MUL R12, R10, R11
  ADD R8, R8, R12
  ADD R9, R9, R1
  CMP R9, R2
  BRn LOOP
ADD R9, R5, R0
STR R9, R8
RET
"""

SAXPY_ASM = """
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx
CONST R1, #0
LDR R1, R1
CONST R2, #1
ADD R3, R2, R0
LDR R3, R3
CONST R4, #5
ADD R5, R4, R0
LDR R5, R5
MUL R6, R1, R3
ADD R6, R6, R5
CONST R7, #9
ADD R8, R7, R0
STR R8, R6
RET
"""

POLY_ASM = """
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx
CONST R1, #0
ADD R2, R1, R0
LDR R2, R2
MUL R3, R2, R2
ADD R3, R3, R2
CONST R4, #1
ADD R3, R3, R4
CONST R5, #4
ADD R6, R5, R0
STR R6, R3
RET
"""

VECADD6_ASM = """
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx
CONST R1, #0
CONST R2, #6
CONST R3, #12
ADD R4, R1, R0
LDR R4, R4
ADD R5, R2, R0
LDR R5, R5
ADD R6, R4, R5
ADD R7, R3, R0
STR R7, R6
RET
"""


class TestAssemblerEncoding:
    """Tests for individual instruction encoding correctness."""

    def test_arithmetic_add(self):
        from assembler import assemble
        result = assemble("ADD R0, R1, R2")
        assert result['program'][0] == 0x3012

    def test_arithmetic_sub(self):
        from assembler import assemble
        result = assemble("SUB R7, R0, R7")
        assert result['program'][0] == 0x4707

    def test_arithmetic_mul_special_regs(self):
        from assembler import assemble
        result = assemble("MUL R0, %blockIdx, %blockDim")
        assert result['program'][0] == 0x50DE

    def test_arithmetic_div(self):
        from assembler import assemble
        result = assemble("DIV R6, R0, R2")
        assert result['program'][0] == 0x6602

    def test_const_encoding(self):
        from assembler import assemble
        result = assemble("CONST R2, #8")
        assert result['program'][0] == 0x9208

    def test_const_zero(self):
        from assembler import assemble
        result = assemble("CONST R1, #0")
        assert result['program'][0] == 0x9100

    def test_ldr_encoding(self):
        from assembler import assemble
        result = assemble("LDR R4, R4")
        assert result['program'][0] == 0x7440

    def test_str_encoding(self):
        from assembler import assemble
        result = assemble("STR R7, R6")
        assert result['program'][0] == 0x8076

    def test_cmp_encoding(self):
        from assembler import assemble
        result = assemble("CMP R9, R2")
        assert result['program'][0] == 0x2092

    def test_ret_encoding(self):
        from assembler import assemble
        result = assemble("RET")
        assert result['program'][0] == 0xF000

    def test_nop_encoding(self):
        from assembler import assemble
        result = assemble("NOP")
        assert result['program'][0] == 0x0000

    def test_threadidx_register(self):
        from assembler import assemble
        result = assemble("ADD R0, R0, %threadIdx")
        assert result['program'][0] == 0x300F


class TestAssemblerLabels:
    """Tests for label resolution and branch encoding."""

    def test_brn_label_resolution(self):
        from assembler import assemble
        source = "CONST R0, #0\nLOOP:\nADD R0, R0, R1\nCMP R0, R2\nBRn LOOP\nRET"
        result = assemble(source)
        brn_instr = result['program'][3]  # BRn is 4th instruction (index 3)
        opcode = (brn_instr >> 12) & 0xF
        nzp = (brn_instr >> 9) & 0x7
        target = brn_instr & 0xFF
        assert opcode == 0x1
        assert nzp == 0b100  # N only
        assert target == 1   # LOOP is at instruction index 1

    def test_brzp_encoding(self):
        from assembler import assemble
        source = "SKIP:\nNOP\nBRzp SKIP"
        result = assemble(source)
        brzp_instr = result['program'][1]
        nzp = (brzp_instr >> 9) & 0x7
        target = brzp_instr & 0xFF
        assert nzp == 0b011  # Z and P bits
        assert target == 0   # SKIP at instruction 0

    def test_brnzp_unconditional(self):
        from assembler import assemble
        source = "START:\nNOP\nBRnzp START"
        result = assemble(source)
        br_instr = result['program'][1]
        nzp = (br_instr >> 9) & 0x7
        assert nzp == 0b111  # all bits set = unconditional


class TestAssemblerDirectives:
    """Tests for .threads and .data directives."""

    def test_threads_directive(self):
        from assembler import assemble
        source = ".threads 8\nRET"
        result = assemble(source)
        assert result['threads'] == 8

    def test_data_directive(self):
        from assembler import assemble
        source = ".data 1 2 3 4\n.data 5 6 7 8\nRET"
        result = assemble(source)
        assert result['data'] == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_comments_stripped(self):
        from assembler import assemble
        source = "ADD R0, R1, R2  ; add values\nRET ; done"
        result = assemble(source)
        assert len(result['program']) == 2
        assert result['program'][0] == 0x3012


class TestAssemblerFullPrograms:
    """Tests assembling complete kernel programs against known binaries."""

    def test_matadd_full_encoding(self):
        from assembler import assemble
        result = assemble(MATADD_ASM)
        assert result['program'] == MATADD_PROGRAM, (
            f"Matadd encoding mismatch.\n"
            f"Expected: {[hex(x) for x in MATADD_PROGRAM]}\n"
            f"Got:      {[hex(x) for x in result['program']]}"
        )

    def test_matmul_full_encoding(self):
        from assembler import assemble
        result = assemble(MATMUL_ASM)
        assert result['program'] == MATMUL_PROGRAM, (
            f"Matmul encoding mismatch.\n"
            f"Expected: {[hex(x) for x in MATMUL_PROGRAM]}\n"
            f"Got:      {[hex(x) for x in result['program']]}"
        )


class TestSimulator:
    """Tests for the functional GPU simulator."""

    def test_matadd_result(self):
        """Matrix addition: two 1x8 vectors, 8 threads."""
        from simulator import simulate
        data = [0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7]
        result = simulate(MATADD_PROGRAM, data, thread_count=8)
        expected = [0, 2, 4, 6, 8, 10, 12, 14]
        for i, exp in enumerate(expected):
            assert result['data_memory'][16 + i] == exp, (
                f"matadd[{i}]: expected {exp}, got {result['data_memory'][16+i]}"
            )

    def test_matadd_blocks(self):
        """Matrix addition should use 2 blocks (8 threads / 4 per block)."""
        from simulator import simulate
        data = [0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7]
        result = simulate(MATADD_PROGRAM, data, thread_count=8)
        assert result['num_blocks'] == 2

    def test_matmul_result(self):
        """2x2 matrix multiplication: A=[[1,2],[3,4]], B=[[1,2],[3,4]]."""
        from simulator import simulate
        data = [1, 2, 3, 4, 1, 2, 3, 4]
        result = simulate(MATMUL_PROGRAM, data, thread_count=4)
        # C = A @ B = [[7,10],[15,22]]
        expected = [7, 10, 15, 22]
        for i, exp in enumerate(expected):
            assert result['data_memory'][8 + i] == exp, (
                f"matmul[{i}]: expected {exp}, got {result['data_memory'][8+i]}"
            )

    def test_matmul_single_block(self):
        """4 threads with 4 per block should be 1 block."""
        from simulator import simulate
        data = [1, 2, 3, 4, 1, 2, 3, 4]
        result = simulate(MATMUL_PROGRAM, data, thread_count=4)
        assert result['num_blocks'] == 1

    def test_saxpy(self):
        """SAXPY: C[i] = a * X[i] + Y[i], a=3, X=[2,4,6,8], Y=[1,3,5,7]."""
        from assembler import assemble
        from simulator import simulate
        assembled = assemble(SAXPY_ASM)
        data = [3, 2, 4, 6, 8, 1, 3, 5, 7]
        result = simulate(assembled['program'], data, thread_count=4)
        expected = [7, 15, 23, 31]  # 3*2+1, 3*4+3, 3*6+5, 3*8+7
        for i, exp in enumerate(expected):
            assert result['data_memory'][9 + i] == exp, (
                f"saxpy[{i}]: expected {exp}, got {result['data_memory'][9+i]}"
            )

    def test_polynomial(self):
        """Polynomial: C[i] = X[i]^2 + X[i] + 1 for X=[2,3,4,5]."""
        from assembler import assemble
        from simulator import simulate
        assembled = assemble(POLY_ASM)
        data = [2, 3, 4, 5]
        result = simulate(assembled['program'], data, thread_count=4)
        expected = [7, 13, 21, 31]  # 4+2+1, 9+3+1, 16+4+1, 25+5+1
        for i, exp in enumerate(expected):
            assert result['data_memory'][4 + i] == exp, (
                f"poly[{i}]: expected {exp}, got {result['data_memory'][4+i]}"
            )

    def test_nonaligned_threads(self):
        """6 threads with 4 per block: block0=4 threads, block1=2 threads."""
        from assembler import assemble
        from simulator import simulate
        assembled = assemble(VECADD6_ASM)
        data = [1, 2, 3, 4, 5, 6, 10, 20, 30, 40, 50, 60]
        result = simulate(assembled['program'], data, thread_count=6)
        expected = [11, 22, 33, 44, 55, 66]
        for i, exp in enumerate(expected):
            assert result['data_memory'][12 + i] == exp, (
                f"vecadd6[{i}]: expected {exp}, got {result['data_memory'][12+i]}"
            )
        assert result['num_blocks'] == 2

    def test_data_memory_size(self):
        """Data memory must be 256 entries."""
        from simulator import simulate
        result = simulate([0xF000], [], thread_count=1)
        assert len(result['data_memory']) == 256

    def test_unchanged_memory(self):
        """Memory not written to should remain at initial value."""
        from simulator import simulate
        data = [42, 99]
        result = simulate([0xF000], data, thread_count=1)
        assert result['data_memory'][0] == 42
        assert result['data_memory'][1] == 99
        assert result['data_memory'][2] == 0  # uninitialized


class TestEdgeCaseSemantics:
    """Tests for subtle architectural semantics that require deep Verilog understanding."""

    def test_8bit_unsigned_overflow(self):
        """Arithmetic must wrap at 8 bits: 200 + 100 = 300 -> 44."""
        from assembler import assemble
        from simulator import simulate
        source = """
        .threads 1
        CONST R0, #200
        CONST R1, #100
        ADD R2, R0, R1
        CONST R3, #0
        STR R3, R2
        RET
        """
        assembled = assemble(source)
        result = simulate(assembled['program'], assembled['data'], assembled['threads'])
        assert result['data_memory'][0] == 44, (
            f"Expected 44 (300 & 0xFF), got {result['data_memory'][0]}"
        )

    def test_mul_8bit_overflow(self):
        """MUL must also wrap at 8 bits: 16 * 17 = 272 -> 16."""
        from assembler import assemble
        from simulator import simulate
        source = """
        .threads 1
        CONST R0, #16
        CONST R1, #17
        MUL R2, R0, R1
        CONST R3, #0
        STR R3, R2
        RET
        """
        assembled = assemble(source)
        result = simulate(assembled['program'], assembled['data'], assembled['threads'])
        assert result['data_memory'][0] == 16, (
            f"Expected 16 (272 & 0xFF), got {result['data_memory'][0]}"
        )

    def test_special_register_write_protection(self):
        """Writes to hardware-mapped registers (blockIdx/blockDim/threadIdx) must be silently ignored."""
        from assembler import assemble
        from simulator import simulate
        source = """
        .threads 1
        CONST R0, #99
        ADD R0, R0, %blockIdx
        ADD %blockIdx, R0, R0
        CONST R1, #0
        STR R1, %blockIdx
        CONST R2, #1
        STR R2, R0
        RET
        """
        assembled = assemble(source)
        result = simulate(assembled['program'], assembled['data'], assembled['threads'])
        # blockIdx was not overwritten — still 0
        assert result['data_memory'][0] == 0, (
            f"blockIdx should be 0 (write-protected), got {result['data_memory'][0]}"
        )
        # R0 retains its computed value (99 + 0 = 99)
        assert result['data_memory'][1] == 99, (
            f"R0 should be 99, got {result['data_memory'][1]}"
        )

    def test_cmp_brz_equal_operands(self):
        """BRz must branch when CMP operands are equal (unsigned diff == 0)."""
        from assembler import assemble
        from simulator import simulate
        source = """
        .threads 1
        CONST R0, #5
        CONST R1, #5
        CMP R0, R1
        BRz EQUAL
        CONST R2, #0
        CONST R3, #0
        STR R3, R2
        RET
        EQUAL:
        CONST R2, #42
        CONST R3, #0
        STR R3, R2
        RET
        """
        assembled = assemble(source)
        result = simulate(assembled['program'], assembled['data'], assembled['threads'])
        assert result['data_memory'][0] == 42, (
            f"Expected 42 (BRz should have branched), got {result['data_memory'][0]}"
        )

    def test_cmp_brn_unequal_operands(self):
        """BRn must branch when CMP operands differ (unsigned diff != 0), regardless of order."""
        from assembler import assemble
        from simulator import simulate
        # Test with first < second: 3 vs 7
        source = """
        .threads 1
        CONST R0, #3
        CONST R1, #7
        CMP R0, R1
        BRn NOTEQ
        CONST R2, #0
        CONST R3, #0
        STR R3, R2
        RET
        NOTEQ:
        CONST R2, #77
        CONST R3, #0
        STR R3, R2
        RET
        """
        assembled = assemble(source)
        result = simulate(assembled['program'], assembled['data'], assembled['threads'])
        assert result['data_memory'][0] == 77, (
            f"Expected 77 (BRn should branch on unequal), got {result['data_memory'][0]}"
        )

    def test_brp_never_taken(self):
        """BRp must never be taken — unsigned CMP cannot produce the P flag."""
        from assembler import assemble
        from simulator import simulate
        source = """
        .threads 1
        CONST R0, #5
        CONST R1, #10
        CMP R0, R1
        BRp WRONG
        CONST R2, #1
        CONST R3, #0
        STR R3, R2
        RET
        WRONG:
        CONST R2, #99
        CONST R3, #0
        STR R3, R2
        RET
        """
        assembled = assemble(source)
        result = simulate(assembled['program'], assembled['data'], assembled['threads'])
        assert result['data_memory'][0] == 1, (
            f"Expected 1 (BRp must NOT branch), got {result['data_memory'][0]}"
        )


class TestEndToEnd:
    """Tests combining assembler and simulator in a full pipeline."""

    def test_e2e_matadd(self):
        from assembler import assemble
        from simulator import simulate
        source = ".threads 8\n.data 0 1 2 3 4 5 6 7\n.data 0 1 2 3 4 5 6 7\n" + MATADD_ASM
        assembled = assemble(source)
        assert assembled['threads'] == 8
        result = simulate(
            assembled['program'], assembled['data'], assembled['threads']
        )
        expected = [0, 2, 4, 6, 8, 10, 12, 14]
        for i, exp in enumerate(expected):
            assert result['data_memory'][16 + i] == exp

    def test_e2e_matmul(self):
        from assembler import assemble
        from simulator import simulate
        source = ".threads 4\n.data 1 2 3 4\n.data 1 2 3 4\n" + MATMUL_ASM
        assembled = assemble(source)
        assert assembled['threads'] == 4
        result = simulate(
            assembled['program'], assembled['data'], assembled['threads']
        )
        expected = [7, 10, 15, 22]
        for i, exp in enumerate(expected):
            assert result['data_memory'][8 + i] == exp

    def test_e2e_polynomial(self):
        from assembler import assemble
        from simulator import simulate
        source = ".threads 4\n.data 2 3 4 5\n" + POLY_ASM
        assembled = assemble(source)
        result = simulate(
            assembled['program'], assembled['data'], assembled['threads']
        )
        expected = [7, 13, 21, 31]
        for i, exp in enumerate(expected):
            assert result['data_memory'][4 + i] == exp
