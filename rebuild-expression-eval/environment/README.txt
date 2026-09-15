evalx - Expression Evaluator

Evaluates integer expressions from the command line.

Usage:
  evalx '<expression>'
  evalx -x '<expression>'     (hexadecimal output)
  evalx -b '<expression>'     (binary output)
  evalx -f <file>             (evaluate from file, one per line)

Supports decimal and hexadecimal (0x...) integer literals.
Includes various operators and built-in functions.
Lines starting with # are treated as comments in file mode.
