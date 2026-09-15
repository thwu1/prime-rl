`/app/ppu_scroll.py` implements a NES PPU scroll register state machine (v/t/x/w registers, $2000/$2002/$2005/$2006 write handlers). It contains multiple bugs causing incorrect register state. The `PPUScrollState` class must retain its `set_state(v=, t=, x=, w=)` method for direct register manipulation, and the module-level `simulate_register_writes(operations)` function must remain functional after your fixes.

`/app/renderer.c` is a C-language NES PPU background tile renderer that also contains multiple bugs. A `Makefile` at `/app/Makefile` compiles it; running `make -C /app` produces the `/app/renderer` binary.

Binary PPU data at `/app/`: `chr_rom.bin` (4096 bytes, 256 tiles, 2bpp format), `vram.bin` (2048 bytes, two 1024-byte nametables with 64-byte attribute tables at offset 960), `palette.bin` (32 bytes). Vertical mirroring.

`/app/register_trace.json` specifies PPU register write sequences for four split-scroll regions: initial writes before rendering plus mid-frame writes at scanline boundaries via $2005 and $2006.

`/app/reference.json` contains the SHA-256 of the correct 61440-byte framebuffer (256×240, one palette-index byte per pixel, row-major), per-scanline CRC-32 checksums, and spot pixel values.

Fix all bugs in `/app/ppu_scroll.py` and create `/app/render_frame.py` — a pipeline that drives the corrected state machine through the register trace, renders background tiles for all 240 scanlines following NES PPU rendering semantics, and writes the framebuffer to `/app/output/frame.bin`. Every pixel must be a valid NES palette index (0x00–0x3F), and the frame must contain more than 30% non-backdrop (0x0F) pixels. The output must match the reference SHA-256.

Fix all bugs in `/app/renderer.c` and compile it with `make -C /app`. Create `/app/render_config.txt` — the configuration file the C renderer reads — by simulating the corrected PPU state machine on the register trace to derive per-region scroll positions. The file format is:

```
<mirroring_mode>
<pattern_table_byte_offset>
<number_of_regions>
<start_scanline> <end_scanline> <scroll_x_9bit> <scroll_y_9bit>
...
```

Run the compiled renderer from `/app` to produce `/app/output/frame_0.bin`. Both `frame.bin` and `frame_0.bin` must match the reference SHA-256.