# tiny-gpu

A minimal GPU implementation in SystemVerilog optimized for learning about how GPUs work from the ground up.

## Architecture

### GPU

tiny-gpu is built to execute a single kernel at a time.

To launch a kernel:
1. Load global program memory with the kernel code
2. Load data memory with the necessary data
3. Specify the number of threads to launch in the device control register
4. Launch the kernel by setting the start signal to high

The GPU consists of:
- Device control register (stores thread_count)
- Dispatcher (distributes blocks of threads to available cores)
- Variable number of compute cores (default: 2)
- Memory controllers for data memory and program memory

### Memory

- **Data memory**: 8-bit addressable (256 rows), 8-bit data values (0-255)
- **Program memory**: 8-bit addressable (256 rows), 16-bit instructions
- Memory controllers throttle requests based on external memory bandwidth

### Core

Each core processes one **block** at a time. For each thread in a block, the core has dedicated:
- ALU (arithmetic-logic unit)
- LSU (load-store unit)
- Register file (16 registers)
- Program counter with NZP branching

### Execution Pipeline

Each core follows this control flow for each instruction:
1. **FETCH** (state 001) - Fetch instruction at current PC from program memory
2. **DECODE** (state 010) - Decode instruction into control signals
3. **REQUEST** (state 011) - Request data from registers or memory
4. **WAIT** (state 100) - Wait for async memory responses
5. **EXECUTE** (state 101) - Execute ALU and PC computations
6. **UPDATE** (state 110) - Update register files, NZP register, and PC

## ISA

11 instructions, each 16 bits wide:

| Opcode (4 bits) | Instruction | Description |
|-----------------|-------------|-------------|
| 0000 | NOP | No operation |
| 0001 | BRnzp | Branch if NZP condition matches |
| 0010 | CMP | Compare two registers, set NZP register |
| 0011 | ADD | Rd = Rs + Rt |
| 0100 | SUB | Rd = Rs - Rt |
| 0101 | MUL | Rd = Rs * Rt |
| 0110 | DIV | Rd = Rs / Rt (integer division) |
| 0111 | LDR | Load from data memory: Rd = mem[Rs] |
| 1000 | STR | Store to data memory: mem[Rs] = Rt |
| 1001 | CONST | Load immediate: Rd = immediate |
| 1111 | RET | End thread execution |

### Instruction Format

General format for arithmetic instructions:
```
[15:12] opcode | [11:8] rd | [7:4] rs | [3:0] rt
```

CONST instruction:
```
[15:12] opcode | [11:8] rd | [7:0] immediate (8-bit value)
```

BRnzp instruction:
```
[15:12] opcode | [11:9] nzp condition | [8] unused | [7:0] target address
```

### Register Layout

Each thread has 16 registers:
- R0 - R12: General purpose (read/write)
- R13: `%blockIdx` (read-only) - current block index
- R14: `%blockDim` (read-only) - threads per block (always THREADS_PER_BLOCK)
- R15: `%threadIdx` (read-only) - thread index within block

## Block Dispatch

Threads are organized into blocks of `THREADS_PER_BLOCK` threads. The dispatcher assigns blocks to available cores. For the last block, the thread count may be fewer than `THREADS_PER_BLOCK`.

The global thread index is computed as: `i = blockIdx * blockDim + threadIdx`

The GPU assumes no branch divergence - all threads within a block follow the same control flow path.

## Example Kernels

### Matrix Addition (1x8)

Adds two 1x8 matrices element-wise using 8 threads:
```
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx         ; i = blockIdx * blockDim + threadIdx
CONST R1, #0                   ; baseA
CONST R2, #8                   ; baseB
CONST R3, #16                  ; baseC
ADD R4, R1, R0                 ; addr(A[i])
LDR R4, R4                     ; load A[i]
ADD R5, R2, R0                 ; addr(B[i])
LDR R5, R5                     ; load B[i]
ADD R6, R4, R5                 ; C[i] = A[i] + B[i]
ADD R7, R3, R0                 ; addr(C[i])
STR R7, R6                     ; store C[i]
RET
```

### Matrix Multiplication (2x2)

Multiplies two 2x2 matrices using 4 threads with a loop:
```
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx         ; i
CONST R1, #1                   ; increment
CONST R2, #2                   ; N
CONST R3, #0                   ; baseA
CONST R4, #4                   ; baseB
CONST R5, #8                   ; baseC
DIV R6, R0, R2                 ; row = i / N
MUL R7, R6, R2
SUB R7, R0, R7                 ; col = i % N
CONST R8, #0                   ; acc = 0
CONST R9, #0                   ; k = 0
LOOP:
  MUL R10, R6, R2
  ADD R10, R10, R9
  ADD R10, R10, R3             ; addr(A[row*N+k])
  LDR R10, R10
  MUL R11, R9, R2
  ADD R11, R11, R7
  ADD R11, R11, R4             ; addr(B[k*N+col])
  LDR R11, R11
  MUL R12, R10, R11
  ADD R8, R8, R12              ; acc += A[row*N+k] * B[k*N+col]
  ADD R9, R9, R1               ; k++
  CMP R9, R2
  BRn LOOP                    ; loop while k < N
ADD R9, R5, R0
STR R9, R8                     ; store C[i]
RET
```
