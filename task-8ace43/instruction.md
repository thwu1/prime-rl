A stripped, compiled binary at `/app/cstore` implements a custom binary serialization format for JSON data. No source code is available. The binary supports three documented subcommands:

- `encode` — reads JSON from stdin, writes the custom binary format to stdout
- `decode` — reads the custom binary format from stdin, writes formatted JSON to stdout
- `info` — reads the custom binary format from stdin, writes metadata summary to stdout

Create a Python reimplementation at `/app/solution.py` with the identical CLI interface (`python3 /app/solution.py encode`, etc.) that produces **byte-identical** output for `encode` and **character-identical** output for `decode` and `info` across all valid inputs and runtime configurations.

The implementation must handle all standard JSON value types (null, booleans, integers, floats, strings, arrays, objects) and correctly replicate every aspect of the binary format including any headers, type encodings, integer and float representations, container serialization, key ordering, checksum mechanisms, and output formatting used by the reference binary. The binary format contains multiple non-obvious design choices that must be discovered through systematic probing.

The binary may also have behaviors influenced by the runtime environment that are not apparent from basic I/O testing alone. Comprehensive analysis using binary inspection tools (`strings`, `objdump`, `readelf`) and system-level tracing (`strace`, `ltrace`) is essential to discover and replicate all operational modes. Your reimplementation must match the reference binary's behavior under all runtime conditions.