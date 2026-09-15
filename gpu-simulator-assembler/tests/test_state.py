
import sys
sys.path.insert(0, '/app')

import pytest
from assembler import assemble
from simulator import TinyGPU


# ---------------------------------------------------------------------------
# Reference programs (binary)
# ---------------------------------------------------------------------------

MATADD_PROGRAM = [
    0x50DE,  # MUL R0, %blockIdx, %blockDim
    0x300F,  # ADD R0, R0, %threadIdx
    0x9100,  # CONST R1, #0
    0x9208,  # CONST R2, #8
    0x9310,  # CONST R3, #16
    0x3410,  # ADD R4, R1, R0
    0x7440,  # LDR R4, R4
    0x3520,  # ADD R5, R2, R0
    0x7550,  # LDR R5, R5
    0x3645,  # ADD R6, R4, R5
    0x3730,  # ADD R7, R3, R0
    0x8076,  # STR R7, R6
    0xF000,  # RET
]

MATMUL_PROGRAM = [
    0x50DE,  # MUL R0, %blockIdx, %blockDim
    0x300F,  # ADD R0, R0, %threadIdx
    0x9101,  # CONST R1, #1
    0x9202,  # CONST R2, #2
    0x9300,  # CONST R3, #0
    0x9404,  # CONST R4, #4
    0x9508,  # CONST R5, #8
    0x6602,  # DIV R6, R0, R2
    0x5762,  # MUL R7, R6, R2
    0x4707,  # SUB R7, R0, R7
    0x9800,  # CONST R8, #0
    0x9900,  # CONST R9, #0
    # LOOP (index 12):
    0x5A62,  # MUL R10, R6, R2
    0x3AA9,  # ADD R10, R10, R9
    0x3AA3,  # ADD R10, R10, R3
    0x7AA0,  # LDR R10, R10
    0x5B92,  # MUL R11, R9, R2
    0x3BB7,  # ADD R11, R11, R7
    0x3BB4,  # ADD R11, R11, R4
    0x7BB0,  # LDR R11, R11
    0x5CAB,  # MUL R12, R10, R11
    0x388C,  # ADD R8, R8, R12
    0x3991,  # ADD R9, R9, R1
    0x2092,  # CMP R9, R2
    0x180C,  # BRn LOOP (12)
    0x3950,  # ADD R9, R5, R0
    0x8098,  # STR R9, R8
    0xF000,  # RET
]

VECSCALE_PROGRAM = [
    0x50DE,  # MUL R0, %blockIdx, %blockDim
    0x300F,  # ADD R0, R0, %threadIdx
    0x9100,  # CONST R1, #0
    0x9204,  # CONST R2, #4
    0x9303,  # CONST R3, #3
    0x3410,  # ADD R4, R1, R0
    0x7440,  # LDR R4, R4
    0x5543,  # MUL R5, R4, R3
    0x3620,  # ADD R6, R2, R0
    0x8065,  # STR R6, R5
    0xF000,  # RET
]

INDEXED_STORE_PROGRAM = [
    0x50DE,  # MUL R0, %blockIdx, %blockDim
    0x300F,  # ADD R0, R0, %threadIdx
    0x910A,  # CONST R1, #10
    0x3110,  # ADD R1, R1, R0
    0x9264,  # CONST R2, #100
    0x3220,  # ADD R2, R2, R0
    0x8012,  # STR R1, R2
    0xF000,  # RET
]


# ===========================================================================
# ASSEMBLER TESTS
# ===========================================================================

class TestAssemblerArithmetic:
    def test_add(self):
        assert assemble("ADD R0, R1, R2") == [0x3012]

    def test_sub(self):
        assert assemble("SUB R3, R4, R5") == [0x4345]

    def test_mul(self):
        assert assemble("MUL R6, R7, R8") == [0x5678]

    def test_div(self):
        assert assemble("DIV R9, R10, R11") == [0x69AB]


class TestAssemblerMemory:
    def test_ldr(self):
        assert assemble("LDR R0, R1") == [0x7010]

    def test_str(self):
        assert assemble("STR R2, R3") == [0x8023]


class TestAssemblerControl:
    def test_nop(self):
        assert assemble("NOP") == [0x0000]

    def test_ret(self):
        assert assemble("RET") == [0xF000]

    def test_const(self):
        assert assemble("CONST R4, #42") == [0x942A]

    def test_cmp(self):
        # CMP: opcode=0010, bits[11:8]=0, rs[7:4], rt[3:0]
        assert assemble("CMP R5, R6") == [0x2056]

    def test_brn(self):
        # BRn #12: opcode=0001, nzp=100, imm=12
        assert assemble("BRn #12") == [0x180C]

    def test_brz(self):
        # BRz #5: opcode=0001, nzp=010 at bits[11:9], imm=5
        assert assemble("BRz #5") == [0x1405]

    def test_brp(self):
        # BRp #3: opcode=0001, nzp=001 at bits[11:9], imm=3
        assert assemble("BRp #3") == [0x1203]

    def test_brnzp(self):
        # BRnzp #0: opcode=0001, nzp=111, imm=0
        assert assemble("BRnzp #0") == [0x1E00]


class TestAssemblerSpecialRegisters:
    def test_blockidx(self):
        assert assemble("ADD R0, %blockIdx, R1") == [0x30D1]

    def test_blockdim(self):
        assert assemble("MUL R0, R1, %blockDim") == [0x501E]

    def test_threadidx(self):
        assert assemble("ADD R0, R0, %threadIdx") == [0x300F]

    def test_simd_id_calc(self):
        # Standard SIMD thread ID computation
        code = "MUL R0, %blockIdx, %blockDim\nADD R0, R0, %threadIdx"
        assert assemble(code) == [0x50DE, 0x300F]


class TestAssemblerLabels:
    def test_simple_label(self):
        code = """
CONST R0, #0
LOOP:
ADD R0, R0, R0
BRn LOOP
RET
"""
        result = assemble(code)
        # LOOP resolves to instruction index 1
        # BRn LOOP: 0001_100_0_00000001 = 0x1801
        assert result[2] == 0x1801

    def test_label_forward_reference_not_needed(self):
        # Labels only need backward references (loops)
        code = """
CONST R0, #5
LOOP:
SUB R0, R0, R0
BRnzp LOOP
"""
        result = assemble(code)
        assert len(result) == 3
        assert result[2] == 0x1E01  # BRnzp to index 1


class TestAssemblerFullProgram:
    def test_matmul_kernel(self):
        source = """\
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
        result = assemble(source)
        assert result == MATMUL_PROGRAM

    def test_comments_and_directives_ignored(self):
        source = """\
.threads 8
.data 0 1 2 3 4 5 6 7
; this is a comment
CONST R0, #42  ; inline comment
RET
"""
        result = assemble(source)
        assert result == [0x902A, 0xF000]


# ===========================================================================
# SIMULATOR TESTS
# ===========================================================================

class TestSimulateMatadd:
    def test_standard_data(self):
        """Matrix addition: [0..7] + [0..7] = [0,2,4,6,8,10,12,14]"""
        gpu = TinyGPU(num_cores=2, threads_per_block=4)
        gpu.load_program(MATADD_PROGRAM)
        gpu.load_data([0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7])
        result = gpu.run(thread_count=8)
        for i in range(8):
            expected = i * 2
            assert result['data_memory'][16 + i] == expected, \
                f"matadd[{i}]: expected {expected}, got {result['data_memory'][16 + i]}"

    def test_different_data(self):
        """Anti-cheat: different data inputs"""
        gpu = TinyGPU(num_cores=2, threads_per_block=4)
        gpu.load_program(MATADD_PROGRAM)
        a = [10, 20, 30, 40, 50, 60, 70, 80]
        b = [1, 2, 3, 4, 5, 6, 7, 8]
        gpu.load_data(a + b)
        result = gpu.run(thread_count=8)
        expected = [11, 22, 33, 44, 55, 66, 77, 88]
        for i in range(8):
            assert result['data_memory'][16 + i] == expected[i], \
                f"matadd_alt[{i}]: expected {expected[i]}, got {result['data_memory'][16 + i]}"


class TestSimulateMatmul:
    def test_standard_data(self):
        """2x2 matmul: [[1,2],[3,4]] @ [[1,2],[3,4]] = [[7,10],[15,22]]"""
        gpu = TinyGPU(num_cores=2, threads_per_block=4)
        gpu.load_program(MATMUL_PROGRAM)
        gpu.load_data([1, 2, 3, 4, 1, 2, 3, 4])
        result = gpu.run(thread_count=4)
        expected = [7, 10, 15, 22]
        for i in range(4):
            assert result['data_memory'][8 + i] == expected[i], \
                f"matmul[{i}]: expected {expected[i]}, got {result['data_memory'][8 + i]}"

    def test_different_data(self):
        """Anti-cheat: [[2,0],[1,3]] @ [[1,1],[0,2]] = [[2,2],[1,7]]"""
        gpu = TinyGPU(num_cores=2, threads_per_block=4)
        gpu.load_program(MATMUL_PROGRAM)
        gpu.load_data([2, 0, 1, 3, 1, 1, 0, 2])
        result = gpu.run(thread_count=4)
        expected = [2, 2, 1, 7]
        for i in range(4):
            assert result['data_memory'][8 + i] == expected[i], \
                f"matmul_alt[{i}]: expected {expected[i]}, got {result['data_memory'][8 + i]}"


class TestSimulateVecscale:
    def test_scale_by_3(self):
        """Vector scale: [2,5,10,7] * 3 = [6,15,30,21]"""
        gpu = TinyGPU(num_cores=2, threads_per_block=4)
        gpu.load_program(VECSCALE_PROGRAM)
        gpu.load_data([2, 5, 10, 7])
        result = gpu.run(thread_count=4)
        expected = [6, 15, 30, 21]
        for i in range(4):
            assert result['data_memory'][4 + i] == expected[i], \
                f"vecscale[{i}]: expected {expected[i]}, got {result['data_memory'][4 + i]}"


class TestSimulateIndexedStore:
    def test_single_block(self):
        """4 threads store (100+i) at address (10+i)"""
        gpu = TinyGPU(num_cores=2, threads_per_block=4)
        gpu.load_program(INDEXED_STORE_PROGRAM)
        result = gpu.run(thread_count=4)
        for i in range(4):
            assert result['data_memory'][10 + i] == 100 + i, \
                f"indexed[{i}]: expected {100 + i}, got {result['data_memory'][10 + i]}"

    def test_multi_block(self):
        """8 threads across 2 blocks store (100+i) at address (10+i)"""
        gpu = TinyGPU(num_cores=2, threads_per_block=4)
        gpu.load_program(INDEXED_STORE_PROGRAM)
        result = gpu.run(thread_count=8)
        for i in range(8):
            assert result['data_memory'][10 + i] == 100 + i, \
                f"indexed_multi[{i}]: expected {100 + i}, got {result['data_memory'][10 + i]}"


class TestIntegration:
    def test_assemble_and_simulate_matadd(self):
        """Assemble matadd from source, run through simulator, verify output"""
        source = """\
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
        program = assemble(source)
        assert program == MATADD_PROGRAM

        gpu = TinyGPU()
        gpu.load_program(program)
        gpu.load_data([5, 10, 15, 20, 25, 30, 35, 40,
                       1, 1, 1, 1, 1, 1, 1, 1])
        result = gpu.run(thread_count=8)
        expected = [6, 11, 16, 21, 26, 31, 36, 41]
        for i in range(8):
            assert result['data_memory'][16 + i] == expected[i]

    def test_assemble_and_simulate_matmul(self):
        """Assemble matmul from source, run through simulator, verify output"""
        source = """\
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
        program = assemble(source)
        assert program == MATMUL_PROGRAM

        # [[3,1],[2,4]] @ [[1,0],[2,1]] = [[5,1],[10,4]]
        gpu = TinyGPU()
        gpu.load_program(program)
        gpu.load_data([3, 1, 2, 4, 1, 0, 2, 1])
        result = gpu.run(thread_count=4)
        expected = [5, 1, 10, 4]
        for i in range(4):
            assert result['data_memory'][8 + i] == expected[i], \
                f"integration_matmul[{i}]: expected {expected[i]}, got {result['data_memory'][8 + i]}"


class TestSimulatorMisc:
    def test_data_memory_size(self):
        """Verify data_memory has 256 entries"""
        gpu = TinyGPU()
        gpu.load_program([0xF000])  # just RET
        result = gpu.run(thread_count=4)
        assert len(result['data_memory']) == 256

    def test_cycles_positive(self):
        """Verify cycles count is returned and positive"""
        gpu = TinyGPU()
        gpu.load_program(MATADD_PROGRAM)
        gpu.load_data([0] * 16)
        result = gpu.run(thread_count=8)
        assert 'cycles' in result
        assert result['cycles'] > 0

    def test_default_params(self):
        """Verify TinyGPU works with default parameters"""
        gpu = TinyGPU()
        gpu.load_program(VECSCALE_PROGRAM)
        gpu.load_data([1, 2, 3, 4])
        result = gpu.run(thread_count=4)
        expected = [3, 6, 9, 12]
        for i in range(4):
            assert result['data_memory'][4 + i] == expected[i]
