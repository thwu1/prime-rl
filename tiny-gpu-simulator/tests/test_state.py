
import pytest
import sys

sys.path.insert(0, '/app')
from simulator import TinyGPU

# =============================================================================
# Reference kernel programs from the tiny-gpu test suite (binary-encoded)
# =============================================================================

# Matrix addition kernel: adds two 1x8 matrices element-wise
# baseA=0, baseB=8, baseC=16, 8 threads
MATADD_PROGRAM = [
    0b0101000011011110,  # MUL R0, %blockIdx, %blockDim
    0b0011000000001111,  # ADD R0, R0, %threadIdx         ; i = blockIdx * blockDim + threadIdx
    0b1001000100000000,  # CONST R1, #0                   ; baseA
    0b1001001000001000,  # CONST R2, #8                   ; baseB
    0b1001001100010000,  # CONST R3, #16                  ; baseC
    0b0011010000010000,  # ADD R4, R1, R0                 ; addr(A[i])
    0b0111010001000000,  # LDR R4, R4                     ; load A[i]
    0b0011010100100000,  # ADD R5, R2, R0                 ; addr(B[i])
    0b0111010101010000,  # LDR R5, R5                     ; load B[i]
    0b0011011001000101,  # ADD R6, R4, R5                 ; C[i] = A[i] + B[i]
    0b0011011100110000,  # ADD R7, R3, R0                 ; addr(C[i])
    0b1000000001110110,  # STR R7, R6                     ; store C[i]
    0b1111000000000000,  # RET
]

# Matrix multiplication kernel: multiplies two 2x2 matrices
# baseA=0, baseB=4, baseC=8, N=2, 4 threads
MATMUL_2X2_PROGRAM = [
    0b0101000011011110,  # MUL R0, %blockIdx, %blockDim
    0b0011000000001111,  # ADD R0, R0, %threadIdx         ; i
    0b1001000100000001,  # CONST R1, #1                   ; increment
    0b1001001000000010,  # CONST R2, #2                   ; N
    0b1001001100000000,  # CONST R3, #0                   ; baseA
    0b1001010000000100,  # CONST R4, #4                   ; baseB
    0b1001010100001000,  # CONST R5, #8                   ; baseC
    0b0110011000000010,  # DIV R6, R0, R2                 ; row = i / N
    0b0101011101100010,  # MUL R7, R6, R2
    0b0100011100000111,  # SUB R7, R0, R7                 ; col = i % N
    0b1001100000000000,  # CONST R8, #0                   ; acc = 0
    0b1001100100000000,  # CONST R9, #0                   ; k = 0
    0b0101101001100010,  # MUL R10, R6, R2                ; LOOP (addr 12)
    0b0011101010101001,  # ADD R10, R10, R9
    0b0011101010100011,  # ADD R10, R10, R3               ; addr(A[row*N+k])
    0b0111101010100000,  # LDR R10, R10
    0b0101101110010010,  # MUL R11, R9, R2
    0b0011101110110111,  # ADD R11, R11, R7
    0b0011101110110100,  # ADD R11, R11, R4               ; addr(B[k*N+col])
    0b0111101110110000,  # LDR R11, R11
    0b0101110010101011,  # MUL R12, R10, R11
    0b0011100010001100,  # ADD R8, R8, R12                ; acc += A*B
    0b0011100110010001,  # ADD R9, R9, R1                 ; k++
    0b0010000010010010,  # CMP R9, R2
    0b0001100000001100,  # BRn LOOP (addr 12)
    0b0011100101010000,  # ADD R9, R5, R0                 ; addr(C[i])
    0b1000000010011000,  # STR R9, R8
    0b1111000000000000,  # RET
]

# Matrix multiplication kernel for 3x3: same structure, different constants
# baseA=0, baseB=9, baseC=18, N=3, 9 threads
MATMUL_3X3_PROGRAM = [
    0b0101000011011110,  # MUL R0, %blockIdx, %blockDim
    0b0011000000001111,  # ADD R0, R0, %threadIdx         ; i
    0b1001000100000001,  # CONST R1, #1                   ; increment
    0b1001001000000011,  # CONST R2, #3                   ; N=3
    0b1001001100000000,  # CONST R3, #0                   ; baseA
    0b1001010000001001,  # CONST R4, #9                   ; baseB=9
    0b1001010100010010,  # CONST R5, #18                  ; baseC=18
    0b0110011000000010,  # DIV R6, R0, R2                 ; row = i / N
    0b0101011101100010,  # MUL R7, R6, R2
    0b0100011100000111,  # SUB R7, R0, R7                 ; col = i % N
    0b1001100000000000,  # CONST R8, #0                   ; acc = 0
    0b1001100100000000,  # CONST R9, #0                   ; k = 0
    0b0101101001100010,  # MUL R10, R6, R2                ; LOOP (addr 12)
    0b0011101010101001,  # ADD R10, R10, R9
    0b0011101010100011,  # ADD R10, R10, R3               ; addr(A[row*N+k])
    0b0111101010100000,  # LDR R10, R10
    0b0101101110010010,  # MUL R11, R9, R2
    0b0011101110110111,  # ADD R11, R11, R7
    0b0011101110110100,  # ADD R11, R11, R4               ; addr(B[k*N+col])
    0b0111101110110000,  # LDR R11, R11
    0b0101110010101011,  # MUL R12, R10, R11
    0b0011100010001100,  # ADD R8, R8, R12                ; acc += A*B
    0b0011100110010001,  # ADD R9, R9, R1                 ; k++
    0b0010000010010010,  # CMP R9, R2
    0b0001100000001100,  # BRn LOOP (addr 12)
    0b0011100101010000,  # ADD R9, R5, R0                 ; addr(C[i])
    0b1000000010011000,  # STR R9, R8
    0b1111000000000000,  # RET
]


# =============================================================================
# Tests for the canonical kernels from the tiny-gpu test suite
# =============================================================================

class TestMatrixAddition:
    def test_matadd_basic(self):
        """1x8 matrix addition with 8 threads across 2 blocks."""
        gpu = TinyGPU(num_cores=2, threads_per_block=4)
        data = [0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7]
        result = gpu.run(MATADD_PROGRAM, data, thread_count=8)
        expected = [a + b for a, b in zip(data[0:8], data[8:16])]
        for i, exp in enumerate(expected):
            assert result[i + 16] == exp, \
                f"matadd index {i}: expected {exp}, got {result[i + 16]}"


class TestMatrixMultiplication:
    def test_matmul_2x2(self):
        """2x2 matrix multiplication with inner-product loop."""
        gpu = TinyGPU(num_cores=2, threads_per_block=4)
        data = [1, 2, 3, 4, 1, 2, 3, 4]
        result = gpu.run(MATMUL_2X2_PROGRAM, data, thread_count=4)
        # [[1,2],[3,4]] * [[1,2],[3,4]] = [[7,10],[15,22]]
        expected = [7, 10, 15, 22]
        for i, exp in enumerate(expected):
            assert result[i + 8] == exp, \
                f"matmul 2x2 index {i}: expected {exp}, got {result[i + 8]}"

    def test_matmul_3x3(self):
        """3x3 matrix multiplication: 9 threads across 3 blocks (last block partial)."""
        gpu = TinyGPU(num_cores=2, threads_per_block=4)
        # A = [[1,2,0],[0,1,2],[2,0,1]], B = [[1,0,1],[0,1,0],[1,0,1]]
        a = [1, 2, 0, 0, 1, 2, 2, 0, 1]
        b = [1, 0, 1, 0, 1, 0, 1, 0, 1]
        data = a + b
        result = gpu.run(MATMUL_3X3_PROGRAM, data, thread_count=9)
        # C = A @ B computed manually:
        # C[0,0]=1*1+2*0+0*1=1, C[0,1]=1*0+2*1+0*0=2, C[0,2]=1*1+2*0+0*1=1
        # C[1,0]=0*1+1*0+2*1=2, C[1,1]=0*0+1*1+2*0=1, C[1,2]=0*1+1*0+2*1=2
        # C[2,0]=2*1+0*0+1*1=3, C[2,1]=2*0+0*1+1*0=0, C[2,2]=2*1+0*0+1*1=3
        expected = [1, 2, 1, 2, 1, 2, 3, 0, 3]
        for i, exp in enumerate(expected):
            assert result[i + 18] == exp, \
                f"matmul 3x3 index {i}: expected {exp}, got {result[i + 18]}"


# =============================================================================
# Tests for custom kernels verifying specific ISA features
# =============================================================================

class TestCustomKernels:
    def test_vector_scale_with_overflow(self):
        """Vector scaling kernel: multiply each element by 3, testing 8-bit wrapping."""
        # Kernel: load x[i], multiply by 3, store at output[i]
        program = [
            0b0101000011011110,  # MUL R0, %blockIdx, %blockDim
            0b0011000000001111,  # ADD R0, R0, %threadIdx
            0b1001000100000000,  # CONST R1, #0  (input base)
            0b1001001000000100,  # CONST R2, #4  (output base)
            0b1001001100000011,  # CONST R3, #3  (scale factor)
            0b0011010000010000,  # ADD R4, R1, R0
            0b0111010001000000,  # LDR R4, R4
            0b0101010101000011,  # MUL R5, R4, R3
            0b0011011000100000,  # ADD R6, R2, R0
            0b1000000001100101,  # STR R6, R5
            0b1111000000000000,  # RET
        ]
        gpu = TinyGPU(num_cores=2, threads_per_block=4)
        data = [2, 5, 7, 100]
        result = gpu.run(program, data, thread_count=4)
        # 2*3=6, 5*3=15, 7*3=21, 100*3=300 -> 300 & 0xFF = 44
        expected = [6, 15, 21, (100 * 3) & 0xFF]
        for i, exp in enumerate(expected):
            assert result[i + 4] == exp, \
                f"vscale index {i}: expected {exp}, got {result[i + 4]}"

    def test_power_kernel_with_loop(self):
        """Compute x^3 for each element using a CMP + BRnzp loop."""
        # Kernel: load x[i], compute x^3 via loop (acc *= x, 3 iterations), store
        program = [
            0b0101000011011110,  # MUL R0, R13, R14
            0b0011000000001111,  # ADD R0, R0, R15
            0b1001000100000001,  # CONST R1, #1       (increment)
            0b1001001000000011,  # CONST R2, #3       (exponent / loop count)
            0b1001001100000000,  # CONST R3, #0       (input base)
            0b1001010000000100,  # CONST R4, #4       (output base)
            0b0011010100110000,  # ADD R5, R3, R0     (addr = base + i)
            0b0111010101010000,  # LDR R5, R5         (x = data[addr])
            0b1001011000000001,  # CONST R6, #1       (acc = 1)
            0b1001011100000000,  # CONST R7, #0       (k = 0)
            0b0101011001100101,  # MUL R6, R6, R5     (LOOP addr=10: acc *= x)
            0b0011011101110001,  # ADD R7, R7, R1     (k++)
            0b0010000001110010,  # CMP R7, R2         (compare k with exponent)
            0b0001100000001010,  # BRn LOOP (addr 10)
            0b0011100001000000,  # ADD R8, R4, R0     (out_addr = base + i)
            0b1000000010000110,  # STR R8, R6         (store acc)
            0b1111000000000000,  # RET
        ]
        gpu = TinyGPU(num_cores=2, threads_per_block=4)
        data = [2, 3, 1, 4]
        result = gpu.run(program, data, thread_count=4)
        # 2^3=8, 3^3=27, 1^3=1, 4^3=64
        expected = [8, 27, 1, 64]
        for i, exp in enumerate(expected):
            assert result[i + 4] == exp, \
                f"power index {i}: expected {exp}, got {result[i + 4]}"

    def test_integer_division_truncation(self):
        """Integer division must truncate toward zero (matching Verilog unsigned division)."""
        # Kernel: load x[i], divide by 3, store
        program = [
            0b0101000011011110,  # MUL R0, %blockIdx, %blockDim
            0b0011000000001111,  # ADD R0, R0, %threadIdx
            0b1001000100000000,  # CONST R1, #0  (input base)
            0b1001001000000100,  # CONST R2, #4  (output base)
            0b1001001100000011,  # CONST R3, #3  (divisor)
            0b0011010000010000,  # ADD R4, R1, R0
            0b0111010001000000,  # LDR R4, R4
            0b0110010101000011,  # DIV R5, R4, R3
            0b0011011000100000,  # ADD R6, R2, R0
            0b1000000001100101,  # STR R6, R5
            0b1111000000000000,  # RET
        ]
        gpu = TinyGPU(num_cores=2, threads_per_block=4)
        data = [7, 11, 15, 20]
        result = gpu.run(program, data, thread_count=4)
        # 7//3=2, 11//3=3, 15//3=5, 20//3=6
        expected = [2, 3, 5, 6]
        for i, exp in enumerate(expected):
            assert result[i + 4] == exp, \
                f"div index {i}: expected {exp}, got {result[i + 4]}"


# =============================================================================
# Tests for block dispatch and hardware configuration
# =============================================================================

class TestBlockDispatch:
    def test_partial_block(self):
        """6 threads with threads_per_block=4: second block has only 2 threads."""
        gpu = TinyGPU(num_cores=2, threads_per_block=4)
        data = [0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7]
        result = gpu.run(MATADD_PROGRAM, data, thread_count=6)
        # Threads 0-5 execute, threads 6-7 do not
        for i in range(6):
            expected = data[i] + data[i + 8]
            assert result[i + 16] == expected, \
                f"partial block index {i}: expected {expected}, got {result[i + 16]}"
        # Verify unexecuted threads did not write
        assert result[22] == 0, f"data[22] should be 0, got {result[22]}"
        assert result[23] == 0, f"data[23] should be 0, got {result[23]}"

    def test_different_block_size(self):
        """Different hardware config: 1 core, threads_per_block=2."""
        gpu = TinyGPU(num_cores=1, threads_per_block=2)
        data = [10, 20, 30, 40, 0, 0, 0, 0, 5, 10, 15, 20]
        result = gpu.run(MATADD_PROGRAM, data, thread_count=4)
        # blockDim=2, so block0: i=0,1 (blockIdx=0), block1: i=2,3 (blockIdx=1)
        # Same global indices, same results
        expected = [15, 30, 45, 60]
        for i, exp in enumerate(expected):
            assert result[i + 16] == exp, \
                f"different config index {i}: expected {exp}, got {result[i + 16]}"
