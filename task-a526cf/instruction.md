A notcurses-compatible cell compositor at `/app/` correctly flattens z-ordered TUI planes into a flat output grid. `./compositor <scene>` reads a scene description and prints per-cell rendered output in text format. The compositor is correct and must not be modified.

The project requires a rasterizer that converts the compositor's flat cell grid into an optimized stream of ANSI escape sequences for direct terminal output. `/app/rasterizer.h` defines the required API. `/app/rasterizer.c` contains stubs that compile but produce no output. `/app/docs/rasterizer_spec.md` specifies the escape sequence format, state model, and optimization requirements.

Implement `rasterize_full()` and `rasterize_diff()` in `/app/rasterizer.c`:

- `rasterize_full()` converts an entire composited cell grid into ANSI escape sequences (CUP cursor positioning, SGR 24-bit color and style codes, and printable characters). It must track SGR drawing state to suppress redundant attribute sequences across consecutive cells and trim trailing blank cells from each row.

- `rasterize_diff()` takes a previous and current cell grid and emits only the escape sequences needed to update cells that changed between frames. It must use CUP positioning to jump between non-adjacent changed cells, rely on implicit cursor advance for adjacent changed cells, and produce output substantially smaller than a full render when few cells change.

Both functions must produce byte streams that, when played through a standard ANSI VT state machine, yield exact reproductions of the compositor's cell grid output (matching every cell's character, foreground/background colors or defaults, and style mask). Output must begin and end with `\033[0m`. Design decisions about when to use SGR reset versus incremental attribute changes, how to structure the state tracker, and the diff algorithm are left to you.

`make` in `/app/` builds the `compositor` binary. It supports `./compositor <scene>` (text), `./compositor -r <scene>` (full rasterize), and `./compositor -d <prev> <curr>` (diff rasterize). Modify only `/app/rasterizer.c`.