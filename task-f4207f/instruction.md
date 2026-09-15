A skeleton 6502 emulator project is provided at `/app/`. It contains a `main.c` driver that loads a raw binary into emulated memory and runs your CPU implementation, plus header file `cpu6502.h` defining the interface.

Your task: implement the CPU core in `/app/cpu6502.c` so that:

1. All 151 legal NMOS 6502 opcodes execute correctly across all 13 addressing modes.
2. All processor status flags (N, V, B, D, I, Z, C) are set correctly for every instruction, including the notoriously tricky **BCD (decimal) mode** for ADC and SBC when the D flag is set. Your implementation must match original NMOS 6502 behavior — for ADC in decimal mode, Z is set from the binary sum, V from binary overflow, and N from bit 7 of the intermediate result after low-nibble decimal correction but before high-nibble correction. For SBC in decimal mode, N, V, Z all come from the binary subtraction.
3. The JMP indirect page-boundary bug is reproduced: `JMP ($xxFF)` fetches the high byte from `$xx00`, not `$xx00+$100`.
4. The `cpu_step()` function returns the exact number of cycles consumed by each instruction, accounting for: page-boundary crossing penalties on indexed and indirect-Y addressing, branch taken/not-taken/page-crossing cycle costs, and the +1 cycle for read-modify-write on absolute,X addressing.
5. BRK pushes PC+2 (not PC+1) and sets the B flag in the pushed status byte. IRQ/NMI must also be dispatchable via `cpu_irq()` and `cpu_nmi()`.

The emulator will be validated against the **Klaus2m5 6502 functional test suite** (`/app/tests/6502_functional_test.bin`), which exercises every legal opcode, addressing mode, flag behavior, stack operation, and decimal-mode edge case. The test binary is loaded at address `$0000` with execution starting at `$0400`. The test passes when PC reaches the final success trap (a `JMP` to itself at the end of the test binary). If PC enters a tight loop at any other address, the test has failed at that point.

Additionally, a set of cycle-count verification programs in `/app/tests/` will confirm your per-instruction cycle accuracy, and an exhaustive BCD ADC test will verify all 131,072 input combinations (256 x 256 x 2 carry states) against a reference implementation.