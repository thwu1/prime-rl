The file `/app/microcode_spec.txt` contains the Intel 8086's internal microcode routines for integer multiplication and division, reconstructed from die-level reverse engineering of the actual silicon. Icarus Verilog (`iverilog`, `vvp`) is installed in the environment.

Produce `/app/results.json` with cycle-accurate results that faithfully reproduce the microcode behavior described in the spec. Additionally, independently verify the core multiplication engine by implementing it as a synthesizable Verilog module, simulating it, and extracting register traces from the resulting VCD waveform to cross-validate against your primary implementation.

## Required contents of `/app/results.json`

1. `mul_word`: Unsigned 16-bit MUL for operand pairs (0xFFFF, 0xF00F), (0x0003, 0x0005), (0x8000, 0x0002). Each entry: `{"ax": int, "dx": int, "cf": 0|1, "of": 0|1}`.

2. `mul_byte`: Unsigned 8-bit MUL for (0xFF, 0x55), (0x03, 0x07). Each: `{"al": int, "ah": int, "cf": 0|1, "of": 0|1}`.

3. `imul_word`: Signed 16-bit IMUL for (0xFFF9, 0x0007), (0x0003, 0x0005), (0xFFFC, 0xFFFE). Same format as `mul_word`.

4. `div_word`: Unsigned 16-bit DIV for (dx, ax, divisor): (0x0F00, 0xFF00, 0x0FFC), (0x0000, 0x0043, 0x000A), (0x0000, 0x0064, 0x000A). Each: `{"ax": int, "dx": int}` or `{"error": true}`.

5. `div_byte`: Unsigned 8-bit DIV for (ax, divisor): (0x2345, 0x34), (0x0064, 0x0A). Each: `{"al": int, "ah": int}`.

6. `idiv_word`: Signed 16-bit IDIV for (dx, ax, divisor): (0xFFFF, 0xFFE5, 0x0007), (0xFFFF, 0xFFE5, 0xFFF9), (0x0000, 0x001B, 0xFFF9). Each: `{"ax": int, "dx": int}`.

7. `div_overflow`: For (0x0001, 0x0000, 0x0001) and (0x0000, 0x0005, 0x0000). Each: `{"error": true}`.

8. `mul_trace`: Internal register trace for 0xFFFF × 0xF00F. Array of 17 objects (initial state + 16 loop iterations): `{"tmpA": int, "tmpC": int}`.

9. `div_trace`: Internal register trace for DIV with DX=0x0F00, AX=0xFF00, divisor=0x0FFC. Array of 17 objects: `{"tmpA": int, "tmpC": int}`.

10. `verilog_mul_trace`: Cycle-by-cycle trace extracted from the VCD waveform produced by the Verilog simulation of the multiplication engine for 0xFFFF × 0xF00F. Array of 17 objects `{"tmpA": int, "tmpC": int}`, must match `mul_trace`.

11. `verilog_product`: Final product from the Verilog simulation: `{"high": int, "low": int}`.

## Required artifact files

- `/app/corx.v` — Synthesizable Verilog module for the multiplication engine
- `/app/corx_tb.v` — Testbench exercising the module with 0xFFFF × 0xF00F, dumping waveform to `/app/corx_sim.vcd`
- `/app/corx_sim.vcd` — VCD waveform produced by the Icarus Verilog simulation