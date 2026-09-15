Build an Intel 8086 CPU simulator with cycle-accurate timing estimation. The executable must be at `/app/sim86` (compiled binary or script with shebang and execute permission).

Seven pre-assembled 8086 binary programs are at `/app/binaries/*.bin`. No assembly source is provided — use `ndisasm -b 16`, `xxd`, and other binary analysis tools to reverse-engineer their contents. A timing reference table is at `/app/8086_timing.txt`.

## Interface

```
/app/sim86 <binary_file>
/app/sim86 <binary_file> --memdump <output_file> <start_addr> <size>
/app/sim86 <binary_file> --cycles
```

**Standard mode** prints final CPU state after execution halts:

```
ax:<decimal>
bx:<decimal>
cx:<decimal>
dx:<decimal>
sp:<decimal>
bp:<decimal>
si:<decimal>
di:<decimal>
ip:<decimal>
flags:<space-separated set flag names>
cycles:<decimal total cycle count>
```

Flag names from `{CF, PF, AF, ZF, SF, OF}`. Only set flags listed. If none set, print `flags:` with nothing after the colon.

**`--memdump`** additionally writes raw bytes from simulated memory range `[start_addr, start_addr+size)` to the output file.

**`--cycles`** prints per-instruction cycle breakdown instead of register state. Each executed instruction produces one CSV line:

```
<ip_offset>,<base_clocks>,<ea_clocks>,<penalty_clocks>,<total_clocks>
```

Followed by a final line `TOTAL:<total_cycle_count>`.

## Execution Model

64KB memory, all registers and flags start at zero. Load binary at address 0, execute from IP=0, halt when IP reaches or exceeds program size. Flat 16-bit addressing (no segments).

## Required Instruction Set

MOV (all register/memory/immediate forms including accumulator-direct A0-A3), ADD, SUB, CMP, AND, OR, XOR, NOT, NEG, TEST, INC, DEC, SHL/SHR/SAR (by 1 and by CL), ROL/ROR/RCL/RCR, PUSH/POP reg16, XCHG, all conditional jumps (70-7F), JMP short/near, LOOP/LOOPZ/LOOPNZ/JCXZ, CALL near, RET near, LEA, NOP, HLT, immediate group (opcodes 80-83), unary group (F6/F7: TEST/NOT/NEG/MUL/DIV).

Correct MOD/RM decoding is critical — especially the mod=00/rm=110 direct-address special case and sign-extended byte immediates in opcode 83.

## Cycle Estimation

Implement the timing model from `/app/8086_timing.txt`. Each instruction's cycle cost has three components:

- **Base clocks**: determined by instruction type and operand types (reg-reg, reg-mem, etc.)
- **EA clocks**: effective address calculation cost for memory operands, depends on addressing mode
- **Transfer penalty**: +4 clocks for every 16-bit word memory access at an odd address (the 8086 bus requires two cycles for unaligned word transfers)

The total cycle count is the sum across all executed instructions.