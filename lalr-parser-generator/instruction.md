Build a parser generator toolchain at `/app/` that reads context-free grammars and produces compiled native parser binaries through a Make-based build pipeline.

The toolchain has two components:

**`/app/lalr_gen`** — An executable that reads a `.cfg` grammar file (format: `/app/spec/cfg_format.md`) and writes a standalone C source file to stdout. The generated C program accepts a single argument (path to a whitespace-separated token file), prints exactly `accept` or `reject` (with trailing newline), and exits with code 0 in both cases. The generated C must compile cleanly with `gcc -std=c99 -O2 -Wall -Werror -pedantic`.

**`/app/Makefile`** — Must provide:
- `all` target: builds a parser binary for every `.cfg` in `/app/grammars/`, placing generated C source and compiled binaries under `/app/build/`. Parser binaries are named `build/parser-<stem>` (e.g. `build/parser-g1_arith` from `grammars/g1_arith.cfg`). Must compile C source with `gcc -std=c99 -O2 -Wall -Werror -pedantic`.
- `clean` target: removes the build directory.

Test grammars are in `/app/grammars/`. The grammar format spec is at `/app/spec/cfg_format.md`. One grammar is LALR(1) but not SLR(1), so an SLR(1) or LR(0) approach will not pass. Grammars with epsilon productions are included.