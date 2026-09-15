# tiny-gpu

A minimal GPU implementation in SystemVerilog optimized for learning how GPUs work.

## Architecture

### GPU

tiny-gpu executes a single kernel at a time. To launch a kernel:
1. Load program memory with kernel code
2. Load data memory with input data
3. Set thread count in the device control register
4. Assert the start signal

The GPU consists of:
- **Device Control Register (DCR)**: Stores `thread_count` for the active kernel
- **Dispatcher**: Distributes threads as blocks to available compute cores
- **Compute Cores**: Configurable number (`NUM_CORES`, default 2)
- **Memory Controllers**: Interface between cores and external memory with limited bandwidth channels
- **Program Memory**: 8-bit addresses (256 rows), 16-bit data (instructions)
- **Data Memory**: 8-bit addresses (256 rows), 8-bit data, 4 read/write channels

### Core

Each core processes one block at a time. A block contains up to `THREADS_PER_BLOCK` threads (default 4). Each core has:
- 1 Scheduler (manages execution pipeline)
- 1 Fetcher (retrieves instructions from program memory)
- 1 Decoder (decodes instructions into control signals)
- Per-thread: dedicated ALU, LSU, Register File, and Program Counter

### Execution Pipeline

Each core follows this control flow for every instruction:
1. **FETCH** — Retrieve instruction at current PC from program memory
2. **DECODE** — Decode instruction into control signals
3. **REQUEST** — Read register values; initiate memory requests if needed (LDR/STR)
4. **WAIT** — Wait for memory responses (if applicable)
5. **EXECUTE** — Perform ALU computations and PC calculations
6. **UPDATE** — Write results to registers and update program counter

All threads in a block execute the same instruction simultaneously (SIMD). The GPU assumes all threads converge to the same PC after each instruction (no branch divergence).

### Thread Model

The dispatcher organizes the total `thread_count` into blocks of `THREADS_PER_BLOCK` threads. The last block may have fewer threads if `thread_count` is not evenly divisible. Blocks are dispatched to available cores for processing.

## ISA

All instructions are 16 bits. The ISA supports 11 instructions:

| Instruction | Description |
|-------------|-------------|
| NOP         | No operation |
| BRnzp       | Conditional branch — jump to target address if NZP condition matches |
| CMP         | Compare two registers, update NZP flags for subsequent branch |
| ADD         | rd = rs + rt |
| SUB         | rd = rs - rt |
| MUL         | rd = rs * rt |
| DIV         | rd = rs / rt (integer division) |
| LDR         | Load from data memory: rd = mem[rs] |
| STR         | Store to data memory: mem[rs] = rt |
| CONST       | Load immediate: rd = immediate |
| RET         | Signal thread completion |

### Registers

Each thread has 16 registers (8-bit each):
- **R0 – R12**: General purpose (read/write)
- **R13** (`%blockIdx`): Block index (read-only)
- **R14** (`%blockDim`): Threads per block (read-only)
- **R15** (`%threadIdx`): Thread index within block (read-only)

### Branching

`CMP` compares two register values and stores a result in the NZP register. `BRnzp` checks the NZP register against a condition mask and branches to a target address if there is a match.

Branch variants use suffixes to specify which flags to check: `BRn` (negative), `BRz` (zero), `BRp` (positive), `BRnz`, `BRnp`, `BRzp`, `BRnzp` (unconditional).

## Assembly Syntax

```
MNEMONIC OPERANDS     ; comment
LABEL:
```

- **Registers**: `R0`–`R12`, `%blockIdx`, `%blockDim`, `%threadIdx`
- **Immediates**: `#N` (e.g., `#0`, `#8`, `#16`)
- **Labels**: `LABEL:` on its own line; referenced as branch targets
- **Comments**: `; text` to end of line

## Example Kernels

### Matrix Addition (1×8)

Adds two 1×8 matrices element-wise using 8 threads.

```asm
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx         ; i = blockIdx * blockDim + threadIdx
CONST R1, #0                   ; baseA
CONST R2, #8                   ; baseB
CONST R3, #16                  ; baseC
ADD R4, R1, R0                 ; addr(A[i]) = baseA + i
LDR R4, R4                     ; load A[i]
ADD R5, R2, R0                 ; addr(B[i]) = baseB + i
LDR R5, R5                     ; load B[i]
ADD R6, R4, R5                 ; C[i] = A[i] + B[i]
ADD R7, R3, R0                 ; addr(C[i]) = baseC + i
STR R7, R6                     ; store C[i]
RET
```

Data layout: A[0..7] at addresses 0–7, B[0..7] at 8–15, C[0..7] at 16–23.

### Matrix Multiplication (2×2)

Multiplies two 2×2 matrices using 4 threads with a loop.

```asm
MUL R0, %blockIdx, %blockDim
ADD R0, R0, %threadIdx         ; i = blockIdx * blockDim + threadIdx
CONST R1, #1                   ; increment
CONST R2, #2                   ; N (matrix dimension)
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
  BRn LOOP                     ; continue loop
ADD R9, R5, R0                 ; addr(C[i])
STR R9, R8                     ; store result
RET
```

Data layout: A[0..3] at addresses 0–3, B[0..3] at 4–7, C[0..3] at 8–11.

## Source Files

All SystemVerilog source is in `/app/src/`:
- `gpu.sv` — Top-level module with configurable cores/threads
- `core.sv` — Compute core connecting all per-thread units
- `scheduler.sv` — Core execution pipeline state machine
- `decoder.sv` — Instruction decoder producing control signals
- `alu.sv` — Arithmetic-logic unit
- `lsu.sv` — Load-store unit for async memory access
- `registers.sv` — Register file (13 free + 3 read-only)
- `pc.sv` — Program counter with NZP branching
- `fetcher.sv` — Instruction fetcher
- `dispatch.sv` — Block dispatcher
- `controller.sv` — Memory controller with channel arbitration
- `dcr.sv` — Device control register
