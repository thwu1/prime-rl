A compiled, stripped binary at `/app/evalx` implements a custom expression evaluator with non-standard operators, functions, and precedence rules. The only documentation is a minimal usage note at `/app/README.txt`.

Create a functionally equivalent executable at `/app/myeval` that produces identical output to `/app/evalx` for all valid inputs.

The binary supports standard arithmetic and bitwise operations, but also includes non-standard operators and built-in functions. Some functions use embedded constants and algorithms (such as a Feistel-network-based transform) whose parameters cannot feasibly be determined from input-output testing alone — you must extract them from the binary. Reverse engineering tools (`gdb`, `objdump`, `strings`, `strace`, `ltrace`) are installed in the environment.

Your `/app/myeval` must match `/app/evalx` exactly on:
- All operators (standard and non-standard) and their precedence/associativity
- All built-in functions including those with embedded constants
- Output formatting for all flags (`-x`, `-b`, `-f`)
- Integer width semantics (arithmetic vs bitwise operations may differ)
- Error and edge-case handling

You may implement `/app/myeval` in any language available in the environment.