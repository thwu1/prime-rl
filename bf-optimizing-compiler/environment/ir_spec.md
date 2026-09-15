# BF Compiler IR Specification

## Instructions

Each instruction occupies one line in text form. Arguments are space-separated.

| Instruction | Format | Semantics |
|---|---|---|
| ADD_PTR | `ADD_PTR <n>` | ptr += n |
| SUB_PTR | `SUB_PTR <n>` | ptr -= n |
| ADD_DATA | `ADD_DATA <n>` | cell[ptr] += n |
| SUB_DATA | `SUB_DATA <n>` | cell[ptr] -= n |
| OUTPUT | `OUTPUT` | write cell[ptr] as byte to stdout |
| INPUT | `INPUT` | read one byte from stdin into cell[ptr] |
| LOOP_START | `LOOP_START` | if cell[ptr] == 0, jump past matching LOOP_END |
| LOOP_END | `LOOP_END` | if cell[ptr] != 0, jump to matching LOOP_START |
| SET | `SET <n>` | cell[ptr] = n |
| MUL_ADD | `MUL_ADD <offset> <factor>` | cell[ptr+offset] += cell[ptr] * factor |
| SCAN_RIGHT | `SCAN_RIGHT <stride>` | advance ptr right by stride until cell[ptr] == 0 |
| SCAN_LEFT | `SCAN_LEFT <stride>` | advance ptr left by stride until cell[ptr] == 0 |

All arithmetic is unsigned 8-bit with wrapping (mod 256). Tape is 30000 cells, zero-initialized. The `factor` in MUL_ADD may be negative.

## Stats Output

One line per category in this order:

```
contraction: <count>
clear_loop: <count>
copy_mul_loop: <count>
scan_loop: <count>
set_fold: <count>
```

Each value is the number of pattern instances recognized during that category's analysis.
