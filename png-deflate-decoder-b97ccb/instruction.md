The file `/app/decode_png.c` contains a broken PNG image decoder. Running `make -C /app` must produce:

- `/app/decode_png` — CLI tool: `./decode_png input.png output.raw`
- `/app/libdecode_png.so` — shared library exporting the API declared in `/app/decode_png.h`

The decoder currently fails to produce correct output. Both the incomplete sections (marked `TODO`) and some of the ostensibly complete code contain errors that must be identified through testing and analysis.

**Output format:** Raw pixel bytes, row-major, no padding, one unsigned byte per channel, channels in order matching the color type (G, GA, RGB, or RGBA).

**Scope:** Non-interlaced PNGs, color types 0 (grayscale), 2 (RGB), 4 (grayscale+alpha), 6 (RGBA), 8-bit channel depth only.

**Library API:** The shared library must implement all functions declared in `/app/decode_png.h`. The `PngImage` struct fields must be correctly populated on successful decode. The library is loaded and invoked at runtime by the test harness.

**Validation:** 20 tests decode PNG images across multiple color modes, dimensions (1×1 to 200px), compression levels (0–9), and pixel patterns. Decoded output is compared byte-for-byte against a reference decoder. Both CLI and library interfaces are tested. All 20 tests must pass.
