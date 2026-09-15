A stripped ELF binary at `/app/oracle` implements a custom binary serialization format for JSON data. All symbols and debug information have been removed. No source code, documentation, or format specification is provided.

The binary accepts subcommands via its first argument:
- `encode`: reads JSON from stdin, writes custom binary format to stdout
- `decode`: reads custom binary format from stdin, writes JSON to stdout
- `validate`: reads binary format from stdin, prints `VALID` or `INVALID: <reason>`

Create an executable at `/app/reimpl` that is behaviorally identical to `/app/oracle` across all three documented subcommands. For encoding, your output must be byte-identical to the oracle's output for any valid JSON input. For decoding, your output must be character-identical. For validation, your output must match the oracle's verdict.

The binary may have capabilities beyond the three documented subcommands. Fully understanding the format requires more than black-box input/output testing.