Build a complete 8086 CPU simulator. Your simulator executable at `/app/sim8086` must read raw 8086 machine code binary files (flat binary, no headers — as produced by `nasm -f bin`), decode the variable-length instructions, simulate execution on a virtual 8086 CPU, and report the final machine state.

Six test programs of increasing complexity are at `/app/programs/test1` through `/app/programs/test6`. They exercise register-register operations, memory addressing modes, conditional branching, nested loops, shift/accumulate patterns, bitwise logic (AND/OR/XOR/NOT/NEG), and pixel-buffer rendering via nested loops writing to a 64x64 memory-mapped image. `nasm` and `ndisasm` are available in the environment.

Your simulator must correctly handle:
- The full MOD/REG/RM byte encoding with all addressing modes (register direct, memory direct, base, base+displacement)
- Variable-length instruction decoding (1–6 bytes per instruction)
- Byte and word operations
- Arithmetic flag computation (CF, ZF, SF, OF, PF, AF)
- Conditional jump evaluation based on flags

## Output Format

`/app/sim8086 <binary>` must print to stdout:

```
AX: 0xHHHH
BX: 0xHHHH
CX: 0xHHHH
DX: 0xHHHH
SP: 0xHHHH
BP: 0xHHHH
SI: 0xHHHH
DI: 0xHHHH
IP: 0xHHHH
FLAGS: <flags>
```

Each register value as 4-digit uppercase hex with `0x` prefix. `<flags>` is a concatenation of set flag characters in order: `C` (carry), `Z` (zero), `S` (sign), `O` (overflow), `P` (parity), `A` (auxiliary), empty string if none set.

With `--memdump ADDR LEN` (ADDR in hex with 0x prefix, LEN in decimal), additionally output:

```
MEM[0xADDR]: HH HH HH ...
```

showing `LEN` bytes starting at `ADDR` as space-separated 2-digit uppercase hex.