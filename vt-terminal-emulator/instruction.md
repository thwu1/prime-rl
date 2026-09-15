Implement a VT/ANSI terminal state machine in C at `/app/terminal.c`. The API is defined in `/app/terminal.h`, a test driver is at `/app/main.c`, and the build system is at `/app/Makefile`. Running `make -C /app` must produce both the `vtterm` binary and a `libterminal.so` shared library exposing the same API.

In addition to the C implementation, you must deliver two integration artifacts:

**`/app/bindings.py`** — A Python ctypes wrapper (skeleton at `/app/bindings_skel.py`) that loads `/app/libterminal.so`, defines a `CellStruct` matching the C `Cell` type, sets `argtypes`/`restype` for every API function, and provides a `TerminalEmulator` class whose `get_state()` returns the same JSON structure as `vtterm`'s stdout output.

**`/app/tmux_oracle.sh`** — A shell script (skeleton at `/app/tmux_oracle_skel.sh`) that uses tmux as a reference terminal emulator for validation. It accepts `WIDTH HEIGHT` arguments, reads raw bytes from stdin, creates a headless tmux session of those dimensions, feeds the input to the session's PTY, captures the screen via `tmux capture-pane`, and prints one line per terminal row to stdout.

## Required capabilities

**Character output**: printable ASCII (0x20-0x7E) placed at cursor with current pen attributes. Line wrapping must use pending-wrap semantics — writing at the last column sets a deferred wrap flag; the next printable character triggers CR+LF before placement.

**Control characters**: `\n` (line feed — move cursor down, scroll if at bottom of scroll region), `\r` (carriage return), `\t` (tab to next 8-column boundary), `\b` (backspace).

**CSI sequences** (`ESC [` ...): cursor movement (`A`/`B`/`C`/`D`/`E`/`F`/`G`/`H`/`f`/`d`), erase (`J`/`K`), insert/delete lines (`L`/`M`), insert/delete/erase characters (`@`/`P`/`X`), scroll (`S`/`T`), set scroll region (`r`), save/restore cursor (`s`/`u`).

**SGR** (`ESC [ ... m`): reset (0), bold (1), dim (2), italic (3), underline (4), blink (5), reverse (7), invisible (8), strikethrough (9), with selective disable via 22-25 and 27-29. Standard 16 colors (30-37, 40-47, 90-97, 100-107), 256-color (38;5;N / 48;5;N), 24-bit RGB (38;2;R;G;B / 48;2;R;G;B), default color (39/49).

**ESC sequences**: save cursor (`ESC 7`), restore cursor (`ESC 8`), index (`ESC D`), next line (`ESC E`), reverse index (`ESC M`). Gracefully consume OSC strings (`ESC ]` ... BEL/ST) and DEC private modes (`CSI ?` ...) without crashing.

**Scroll regions** (DECSTBM via `CSI r`): line feed at the bottom margin and reverse index at the top margin scroll only within the region. Lines outside the region are unaffected.

**Partial sequences**: escape sequences split across multiple `terminal_process()` calls must be handled via persistent parser state.

The color palette (indices 0-15, 6x6x6 cube for 16-231, grayscale for 232-255) and default colors are specified in `/app/terminal.h`. Erase operations fill cells with the current pen's background color.