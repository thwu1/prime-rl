# p1_constprop.asm
# Computes n * 60 + 30 through multi-level constant variable chains.
# Requires cascading constant propagation through 4 levels.

READ_INT
STORE n

# Level 0: direct constants
PUSH_INT 3
STORE a
PUSH_INT 4
STORE b

# Level 1: c = a * b = 12
LOAD a
LOAD b
MUL
STORE c

# Level 0: another constant
PUSH_INT 5
STORE d

# Level 2: e = c * d = 60
LOAD c
LOAD d
MUL
STORE e

# Level 0: divisor
PUSH_INT 2
STORE f

# Level 3: g = e / f = 30
LOAD e
LOAD f
DIV
STORE g

# Identity bloat: e2 = e + 0
LOAD e
PUSH_INT 0
ADD
STORE e2

# Identity bloat: factor = e2 * 1
LOAD e2
PUSH_INT 1
MUL
STORE factor

# result = n * factor + g
LOAD n
LOAD factor
MUL
LOAD g
ADD
STORE result

LOAD result
PRINTLN
HALT
