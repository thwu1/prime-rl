# SysY Runtime Library

The following functions are implicitly available in every SysY program (no `#include` needed):

## Input Functions

### `int getint()`
Reads one integer from stdin (equivalent to C `scanf("%d", &t); return t;`).
Skips leading whitespace, reads an integer.

### `int getch()`
Reads one character from stdin (equivalent to C `scanf("%c", &c); return (int)c;`).
Does NOT skip whitespace.

### `int getarray(int a[])`
Reads an integer `n` from stdin, then reads `n` integers into array `a`.
Returns `n`.
Equivalent to:
```c
int n; scanf("%d", &n);
for (int i = 0; i < n; i++) scanf("%d", &a[i]);
return n;
```

## Output Functions

### `void putint(int a)`
Prints integer `a` to stdout without any trailing newline or space.
Equivalent to `printf("%d", a);`

### `void putch(int a)`
Prints the character with ASCII code `a` to stdout.
Equivalent to `printf("%c", a);`
Common usage: `putch(10)` prints newline, `putch(32)` prints space.

### `void putarray(int n, int a[])`
Prints `n` followed by `:`, then `n` elements of array `a` separated by spaces, then a newline.
Format: `printf("%d:", n); for (int i = 0; i < n; i++) printf(" %d", a[i]); printf("\n");`
Example: `putarray(3, a)` with `a = {10, 20, 30}` prints `3: 10 20 30\n`

## Timing Functions (optional, may be no-ops)

### `void starttime()` / `void stoptime()`
Used for performance benchmarking. An interpreter may implement these as no-ops.
