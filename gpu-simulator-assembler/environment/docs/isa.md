# tiny-gpu Instruction Set Architecture

## Instruction Format

All instructions are 16 bits wide. Fields are decoded from fixed bit positions:

| Bits    | Field | Description                              |
|---------|-------|------------------------------------------|
| [15:12] | opcode | Instruction type (4 bits)               |
| [11:8]  | rd     | Destination register (4 bits)           |
| [7:4]   | rs     | Source register 1 (4 bits)              |
| [3:0]   | rt     | Source register 2 (4 bits)              |
| [7:0]   | imm    | 8-bit immediate (CONST, BRnzp)          |
| [11:9]  | nzp    | Branch condition bits (BRnzp only)      |

## Opcodes

| Opcode | Hex | Mnemonic | Encoding                          | Description                     |
|--------|-----|----------|-----------------------------------|---------------------------------|
| 0000   | 0   | NOP      | —                                 | No operation                    |
| 0001   | 1   | BRnzp    | nzp[11:9], imm[7:0]              | Conditional branch              |
| 0010   | 2   | CMP      | rs[7:4], rt[3:0]                 | Compare rs and rt (signed)      |
| 0011   | 3   | ADD      | rd[11:8], rs[7:4], rt[3:0]       | rd = (rs + rt) mod 256          |
| 0100   | 4   | SUB      | rd[11:8], rs[7:4], rt[3:0]       | rd = (rs - rt) mod 256          |
| 0101   | 5   | MUL      | rd[11:8], rs[7:4], rt[3:0]       | rd = (rs * rt) mod 256          |
| 0110   | 6   | DIV      | rd[11:8], rs[7:4], rt[3:0]       | rd = rs // rt (integer div)     |
| 0111   | 7   | LDR      | rd[11:8], rs[7:4]                | rd = data_mem[rs]               |
| 1000   | 8   | STR      | rs[7:4], rt[3:0]                 | data_mem[rs] = rt               |
| 1001   | 9   | CONST    | rd[11:8], imm[7:0]              | rd = immediate                  |
| 1111   | F   | RET      | —                                 | End thread execution            |

## Registers

16 registers per thread, each 8 bits wide:

| Register | Name        | Access     | Description                    |
|----------|-------------|------------|--------------------------------|
| R0–R12   | General     | Read/Write | General purpose registers      |
| R13      | %blockIdx   | Read-only  | Current block index            |
| R14      | %blockDim   | Read-only  | Threads per block              |
| R15      | %threadIdx  | Read-only  | Thread index within block      |

## CMP Instruction

CMP compares two register values using signed subtraction semantics:
- If rs < rt → NZP = N (negative), encoded as 0b100
- If rs == rt → NZP = Z (zero), encoded as 0b010
- If rs > rt → NZP = P (positive), encoded as 0b001

The NZP result is stored in a per-thread NZP register for use by subsequent BRnzp instructions.

## BRnzp Instruction

Branches to address `imm` if the current NZP register matches the condition:
- Bits [11:9] specify which NZP bits to test
- Branch is taken if `(NZP & condition) != 0`
- Common forms: BRn (100), BRz (010), BRp (001), BRnzp (111 = unconditional)

## Arithmetic

All arithmetic operates on 8-bit values. Results wrap modulo 256.

## Memory

- Data memory: 256 entries × 8 bits (read/write via LDR/STR)
- Program memory: 256 entries × 16 bits (instructions)

## GPU Default Configuration

- NUM_CORES = 2
- THREADS_PER_BLOCK = 4
- DATA_MEM_NUM_CHANNELS = 4
- PROGRAM_MEM_NUM_CHANNELS = 1

## Execution Model

All threads in a block share the same program counter (no branch divergence).
The core pipeline stages are: IDLE → FETCH → DECODE → REQUEST → WAIT → EXECUTE → UPDATE.
The dispatcher assigns blocks of threads to available cores. Each core processes one block at a time.
Global thread index is computed as: `blockIdx * blockDim + threadIdx`.
