The Earthrise 2D graphics processor is a custom 16-bit instruction set architecture for drawing shapes to a framebuffer. SystemVerilog implementations of all drawing primitives are provided in `/app/hardware/`. The ISA specification is in `/app/docs/isa.md`.

Implement a software emulator at `/app/emulator.py` that:

- Reads Earthrise programs from hex instruction files (one 4-digit hex instruction per line, `#` comments)
- Decodes and executes the full Earthrise instruction set, faithfully replicating the exact pixel output of the hardware drawing modules
- Writes the resulting 160x120 framebuffer as a 19200-byte raw file (one byte per pixel, row-major, top-to-bottom)

Usage: `python3 /app/emulator.py <input.hex> <output.raw>`

The hardware modules in `/app/hardware/` define the exact drawing behavior your emulator must replicate. They include modules for line rasterization, circle rasterization, rectangle drawing (composed of line draws), and filled triangle rasterization via edge function evaluation with incremental half-plane testing. Each module uses a specific state machine structure with non-blocking assignments that govern update ordering across clock cycles — naive line-by-line translation from SystemVerilog to Python will produce incorrect results in several modules. You must understand the hardware semantics to produce pixel-identical output.

Test programs are provided in `/app/programs/`.