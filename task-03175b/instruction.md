Build a tool at `/app/sim86.py` that operates in two modes on raw Intel 8086 machine code binaries in `/app/programs/`:

**Decode mode** (`python3 /app/sim86.py decode <binary_file>`): Disassemble the binary into NASM-compatible 16-bit Intel assembly printed to stdout. Output must begin with `bits 16` and, when fed back through `nasm -f bin`, produce a binary byte-identical to the input. Use `ndisasm -b 16 <file>` for reference disassembly and `xxd` for hex inspection — note that `ndisasm` output is NOT directly reassemblable by NASM, so your decoder must produce valid NASM syntax that round-trips to identical bytes.

**Exec mode** (`python3 /app/sim86.py exec <binary_file>`): Load binary at address 0, simulate execution starting at IP=0 until IP reaches or exceeds program length. Track cumulative clock cycles according to the 8086 timing model: each instruction has a base clock cost (from the Intel iAPX 86/88 User's Manual instruction timing reference), and memory-operand instructions additionally incur Effective Address calculation clocks that vary by addressing mode. Print the final machine state as a single JSON object to stdout:

```json
{"ax": 0, "bx": 0, "cx": 0, "dx": 0, "sp": 0, "bp": 0, "si": 0, "di": 0, "ip": 0, "CF": false, "ZF": false, "SF": false, "OF": false, "PF": false, "total_clocks": 0}
```

All 8 general-purpose 16-bit registers as unsigned integers 0-65535, the instruction pointer, arithmetic flags CF, ZF, SF, OF, PF as booleans, and the cumulative total clock count as an integer.

The programs exercise MOV (immediate-to-register for 8-bit and 16-bit, register-to-register, register/memory transfers including byte-width via modrm, moffs accumulator forms, and immediate-to-memory), ADD, SUB, CMP, conditional jumps (JNZ), LOOP, INC, and DEC. Memory addressing modes include direct address, register indirect ([BX], [SI], etc.), base+index ([BX+SI], [BX+DI], [BP+SI], [BP+DI]), and base+index+displacement. The EA calculation cost table distinguishes between these combinations — not all base+index pairs cost the same number of clocks. NASM, ndisasm, and xxd are available in the environment.

```
```