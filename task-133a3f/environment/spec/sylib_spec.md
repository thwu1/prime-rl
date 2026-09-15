# SysY Runtime Library

The SysY runtime provides built-in I/O functions. These are available without any `#include` directive.

## Input Functions

### `int getint()`
Reads one integer from standard input. Skips leading whitespace. Returns the parsed integer value.

### `int getch()`
Reads one character from standard input. Returns its ASCII value as an integer.

### `int getarray(int a[])`
Reads an integer `n` from stdin, then reads `n` integers into array `a`.
Returns `n` (the number of elements read).

## Output Functions

### `void putint(int a)`
Prints integer `a` to standard output (decimal, no trailing newline or space).

### `void putch(int a)`
Prints the character with ASCII value `a` to standard output.
Common values: 10 = newline, 32 = space.

### `void putarray(int n, int a[])`
Prints `n` followed by a colon, then `n` elements of `a` separated by spaces, followed by a newline.
Format: `"n: a[0] a[1] ... a[n-1]\n"`
