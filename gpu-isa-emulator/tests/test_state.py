
import sys
import pytest

sys.path.insert(0, '/app')


class TestAssemblerEncoding:
    """Verify assembler produces correct binary for individual instructions."""

    def test_nop(self):
        from assembler import assemble
        assert assemble("NOP") == [0b0000_0000_0000_0000]

    def test_ret(self):
        from assembler import assemble
        assert assemble("RET") == [0b1111_0000_0000_0000]

    def test_add_with_special_regs(self):
        from assembler import assemble
        # ADD R0, R0, %threadIdx -> opcode=0011 rd=0000 rs=0000 rt=1111
        result = assemble("ADD R0, R0, %threadIdx")
        assert result == [0b0011_0000_0000_1111]

    def test_mul_special_regs(self):
        from assembler import assemble
        # MUL R0, %blockIdx, %blockDim -> opcode=0101 rd=0000 rs=1101 rt=1110
        result = assemble("MUL R0, %blockIdx, %blockDim")
        assert result == [0b0101_0000_1101_1110]

    def test_const(self):
        from assembler import assemble
        # CONST R2, #8 -> opcode=1001 rd=0010 imm=00001000
        result = assemble("CONST R2, #8")
        assert result == [0b1001_0010_0000_1000]

    def test_const_r3_16(self):
        from assembler import assemble
        result = assemble("CONST R3, #16")
        assert result == [0b1001_0011_0001_0000]

    def test_ldr(self):
        from assembler import assemble
        # LDR R4, R4 -> opcode=0111 rd=0100 rs=0100 rt=0000
        result = assemble("LDR R4, R4")
        assert result == [0b0111_0100_0100_0000]

    def test_str(self):
        from assembler import assemble
        # STR R7, R6 -> opcode=1000 rd=0000 rs=0111 rt=0110
        result = assemble("STR R7, R6")
        assert result == [0b1000_0000_0111_0110]

    def test_cmp(self):
        from assembler import assemble
        # CMP R9, R2 -> opcode=0010 rd=0000 rs=1001 rt=0010
        result = assemble("CMP R9, R2")
        assert result == [0b0010_0000_1001_0010]

    def test_sub(self):
        from assembler import assemble
        # SUB R7, R0, R7 -> opcode=0100 rd=0111 rs=0000 rt=0111
        result = assemble("SUB R7, R0, R7")
        assert result == [0b0100_0111_0000_0111]

    def test_div(self):
        from assembler import assemble
        # DIV R6, R0, R2 -> opcode=0110 rd=0110 rs=0000 rt=0010
        result = assemble("DIV R6, R0, R2")
        assert result == [0b0110_0110_0000_0010]


class TestAssemblerPrograms:
    """Verify assembler produces correct machine code for complete programs."""

    def test_matadd_program(self):
        from assembler import assemble
        source = """
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
        expected = [
            0b0101000011011110,  # MUL R0, %blockIdx, %blockDim
            0b0011000000001111,  # ADD R0, R0, %threadIdx
            0b1001000100000000,  # CONST R1, #0
            0b1001001000001000,  # CONST R2, #8
            0b1001001100010000,  # CONST R3, #16
            0b0011010000010000,  # ADD R4, R1, R0
            0b0111010001000000,  # LDR R4, R4
            0b0011010100100000,  # ADD R5, R2, R0
            0b0111010101010000,  # LDR R5, R5
            0b0011011001000101,  # ADD R6, R4, R5
            0b0011011100110000,  # ADD R7, R3, R0
            0b1000000001110110,  # STR R7, R6
            0b1111000000000000,  # RET
        ]
        result = assemble(source)
        for i, (got, exp) in enumerate(zip(result, expected)):
            assert got == exp, (
                f"Instruction {i} mismatch: got {bin(got)}, expected {bin(exp)}"
            )
        assert len(result) == len(expected)

    def test_matmul_program_with_labels(self):
        from assembler import assemble
        source = """
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
        expected = [
            0b0101000011011110,  # MUL R0, %blockIdx, %blockDim
            0b0011000000001111,  # ADD R0, R0, %threadIdx
            0b1001000100000001,  # CONST R1, #1
            0b1001001000000010,  # CONST R2, #2
            0b1001001100000000,  # CONST R3, #0
            0b1001010000000100,  # CONST R4, #4
            0b1001010100001000,  # CONST R5, #8
            0b0110011000000010,  # DIV R6, R0, R2
            0b0101011101100010,  # MUL R7, R6, R2
            0b0100011100000111,  # SUB R7, R0, R7
            0b1001100000000000,  # CONST R8, #0
            0b1001100100000000,  # CONST R9, #0
            # LOOP at address 12
            0b0101101001100010,  # MUL R10, R6, R2
            0b0011101010101001,  # ADD R10, R10, R9
            0b0011101010100011,  # ADD R10, R10, R3
            0b0111101010100000,  # LDR R10, R10
            0b0101101110010010,  # MUL R11, R9, R2
            0b0011101110110111,  # ADD R11, R11, R7
            0b0011101110110100,  # ADD R11, R11, R4
            0b0111101110110000,  # LDR R11, R11
            0b0101110010101011,  # MUL R12, R10, R11
            0b0011100010001100,  # ADD R8, R8, R12
            0b0011100110010001,  # ADD R9, R9, R1
            0b0010000010010010,  # CMP R9, R2
            0b0001100000001100,  # BRn LOOP (target=12)
            0b0011100101010000,  # ADD R9, R5, R0
            0b1000000010011000,  # STR R9, R8
            0b1111000000000000,  # RET
        ]
        result = assemble(source)
        mismatches = [
            i for i, (a, b) in enumerate(zip(result, expected)) if a != b
        ]
        assert len(result) == len(expected), (
            f"Length mismatch: got {len(result)}, expected {len(expected)}"
        )
        assert not mismatches, (
            f"Instruction mismatch at indices {mismatches}: "
            + ", ".join(
                f"{i}: got {bin(result[i])} expected {bin(expected[i])}"
                for i in mismatches
            )
        )


class TestSimulatorMatadd:
    """Verify simulator produces correct output for matrix addition."""

    def test_matadd_basic(self):
        from simulator import simulate
        program = [
            0b0101000011011110,
            0b0011000000001111,
            0b1001000100000000,
            0b1001001000001000,
            0b1001001100010000,
            0b0011010000010000,
            0b0111010001000000,
            0b0011010100100000,
            0b0111010101010000,
            0b0011011001000101,
            0b0011011100110000,
            0b1000000001110110,
            0b1111000000000000,
        ]
        data = [0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7]
        result = simulate(program, data, thread_count=8)

        assert len(result) == 256, "Data memory must be 256 elements"
        expected = [a + b for a, b in zip(data[0:8], data[8:16])]
        for i in range(8):
            assert result[16 + i] == expected[i], (
                f"matadd[{i}]: expected {expected[i]}, got {result[16 + i]}"
            )

    def test_matadd_nonzero(self):
        """Matadd with non-trivial input values."""
        from simulator import simulate
        program = [
            0b0101000011011110,
            0b0011000000001111,
            0b1001000100000000,
            0b1001001000001000,
            0b1001001100010000,
            0b0011010000010000,
            0b0111010001000000,
            0b0011010100100000,
            0b0111010101010000,
            0b0011011001000101,
            0b0011011100110000,
            0b1000000001110110,
            0b1111000000000000,
        ]
        data = [10, 20, 30, 40, 50, 60, 70, 80,
                5, 15, 25, 35, 45, 55, 65, 75]
        result = simulate(program, data, thread_count=8)
        expected = [15, 35, 55, 75, 95, 115, 135, 155]
        for i in range(8):
            assert result[16 + i] == expected[i], (
                f"matadd_nonzero[{i}]: expected {expected[i]}, got {result[16 + i]}"
            )


class TestSimulatorMatmul:
    """Verify simulator produces correct output for matrix multiplication."""

    def test_matmul_identity(self):
        from simulator import simulate
        program = [
            0b0101000011011110,
            0b0011000000001111,
            0b1001000100000001,
            0b1001001000000010,
            0b1001001100000000,
            0b1001010000000100,
            0b1001010100001000,
            0b0110011000000010,
            0b0101011101100010,
            0b0100011100000111,
            0b1001100000000000,
            0b1001100100000000,
            0b0101101001100010,
            0b0011101010101001,
            0b0011101010100011,
            0b0111101010100000,
            0b0101101110010010,
            0b0011101110110111,
            0b0011101110110100,
            0b0111101110110000,
            0b0101110010101011,
            0b0011100010001100,
            0b0011100110010001,
            0b0010000010010010,
            0b0001100000001100,
            0b0011100101010000,
            0b1000000010011000,
            0b1111000000000000,
        ]
        # A = [[1,2],[3,4]], B = [[1,2],[3,4]]
        data = [1, 2, 3, 4, 1, 2, 3, 4]
        result = simulate(program, data, thread_count=4)

        # C = A * B = [[1*1+2*3, 1*2+2*4], [3*1+4*3, 3*2+4*4]]
        #           = [[7, 10], [15, 22]]
        expected = [7, 10, 15, 22]
        for i in range(4):
            assert result[8 + i] == expected[i], (
                f"matmul[{i}]: expected {expected[i]}, got {result[8 + i]}"
            )

    def test_matmul_different_matrices(self):
        from simulator import simulate
        program = [
            0b0101000011011110,
            0b0011000000001111,
            0b1001000100000001,
            0b1001001000000010,
            0b1001001100000000,
            0b1001010000000100,
            0b1001010100001000,
            0b0110011000000010,
            0b0101011101100010,
            0b0100011100000111,
            0b1001100000000000,
            0b1001100100000000,
            0b0101101001100010,
            0b0011101010101001,
            0b0011101010100011,
            0b0111101010100000,
            0b0101101110010010,
            0b0011101110110111,
            0b0011101110110100,
            0b0111101110110000,
            0b0101110010101011,
            0b0011100010001100,
            0b0011100110010001,
            0b0010000010010010,
            0b0001100000001100,
            0b0011100101010000,
            0b1000000010011000,
            0b1111000000000000,
        ]
        # A = [[2,0],[1,3]], B = [[1,4],[0,2]]
        data = [2, 0, 1, 3, 1, 4, 0, 2]
        result = simulate(program, data, thread_count=4)

        # C[0,0] = 2*1+0*0 = 2, C[0,1] = 2*4+0*2 = 8
        # C[1,0] = 1*1+3*0 = 1, C[1,1] = 1*4+3*2 = 10
        expected = [2, 8, 1, 10]
        for i in range(4):
            assert result[8 + i] == expected[i], (
                f"matmul_diff[{i}]: expected {expected[i]}, got {result[8 + i]}"
            )


class TestEndToEnd:
    """End-to-end tests: assemble novel kernels then simulate."""

    def test_axpy_kernel(self):
        """C[i] = alpha * A[i] + B[i] where alpha = 3."""
        from assembler import assemble
        from simulator import simulate

        source = """
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx
CONST R1, #0                   ; baseA
CONST R2, #8                   ; baseB
CONST R3, #16                  ; baseC
CONST R4, #3                   ; alpha
ADD R5, R1, R0
LDR R5, R5                     ; A[i]
ADD R6, R2, R0
LDR R6, R6                     ; B[i]
MUL R7, R4, R5                 ; alpha * A[i]
ADD R8, R7, R6                 ; alpha * A[i] + B[i]
ADD R9, R3, R0
STR R9, R8                     ; store C[i]
RET
"""
        program = assemble(source)
        data_a = [2, 4, 6, 8, 10, 12, 14, 16]
        data_b = [1, 1, 1, 1, 1, 1, 1, 1]
        data = data_a + data_b
        result = simulate(program, data, thread_count=8)

        expected = [3 * a + b for a, b in zip(data_a, data_b)]
        # [7, 13, 19, 25, 31, 37, 43, 49]
        for i in range(8):
            assert result[16 + i] == expected[i], (
                f"axpy[{i}]: expected {expected[i]}, got {result[16 + i]}"
            )

    def test_polynomial_kernel(self):
        """p(x) = 2*x^2 + 3*x + 5 for x in [1, 2, 3, 4]."""
        from assembler import assemble
        from simulator import simulate

        source = """
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx
CONST R1, #0                   ; base_x
CONST R2, #4                   ; base_out
CONST R3, #2                   ; a
CONST R4, #3                   ; b
CONST R5, #5                   ; c
ADD R6, R1, R0
LDR R6, R6                     ; x[i]
MUL R7, R6, R6                 ; x^2
MUL R7, R3, R7                 ; a * x^2
MUL R8, R4, R6                 ; b * x
ADD R9, R7, R8                 ; a*x^2 + b*x
ADD R9, R9, R5                 ; + c
ADD R10, R2, R0
STR R10, R9
RET
"""
        program = assemble(source)
        data = [1, 2, 3, 4]
        result = simulate(program, data, thread_count=4)

        expected = [2 * x * x + 3 * x + 5 for x in data]
        # [10, 19, 32, 49]
        for i in range(4):
            assert result[4 + i] == expected[i], (
                f"poly[{i}]: expected {expected[i]}, got {result[4 + i]}"
            )

    def test_partial_block(self):
        """6 threads with threads_per_block=4 -> blocks of 4 + 2."""
        from assembler import assemble
        from simulator import simulate

        source = """
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx
CONST R1, #0
CONST R2, #6
CONST R3, #2
ADD R4, R1, R0
LDR R4, R4
MUL R5, R3, R4
ADD R6, R2, R0
STR R6, R5
RET
"""
        program = assemble(source)
        data = [5, 10, 15, 20, 25, 30]
        result = simulate(program, data, thread_count=6)

        expected = [10, 20, 30, 40, 50, 60]
        for i in range(6):
            assert result[6 + i] == expected[i], (
                f"partial[{i}]: expected {expected[i]}, got {result[6 + i]}"
            )

    def test_nondefault_config(self):
        """8 threads, num_cores=4, threads_per_block=2."""
        from assembler import assemble
        from simulator import simulate

        source = """
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx
CONST R1, #0
CONST R2, #8
ADD R3, R1, R0
LDR R3, R3
ADD R3, R3, R3
ADD R4, R2, R0
STR R4, R3
RET
"""
        program = assemble(source)
        data = [3, 7, 11, 15, 20, 25, 30, 35]
        result = simulate(program, data, thread_count=8, num_cores=4,
                          threads_per_block=2)

        expected = [6, 14, 22, 30, 40, 50, 60, 70]
        for i in range(8):
            assert result[8 + i] == expected[i], (
                f"config[{i}]: expected {expected[i]}, got {result[8 + i]}"
            )

    def test_data_memory_preserves_input(self):
        """Input data at addresses 0-7 must remain unchanged after matadd."""
        from simulator import simulate
        program = [
            0b0101000011011110,
            0b0011000000001111,
            0b1001000100000000,
            0b1001001000001000,
            0b1001001100010000,
            0b0011010000010000,
            0b0111010001000000,
            0b0011010100100000,
            0b0111010101010000,
            0b0011011001000101,
            0b0011011100110000,
            0b1000000001110110,
            0b1111000000000000,
        ]
        data = [10, 20, 30, 40, 50, 60, 70, 80,
                1, 2, 3, 4, 5, 6, 7, 8]
        result = simulate(program, data, thread_count=8)

        # Input data must be preserved
        for i in range(16):
            assert result[i] == data[i], (
                f"Input data[{i}] modified: expected {data[i]}, got {result[i]}"
            )
        # Unwritten memory must remain zero
        for i in range(24, 256):
            assert result[i] == 0, (
                f"Unwritten data[{i}] is non-zero: {result[i]}"
            )
