# Program: Compute f(N) + g(N) where:
#   f(N) = N * (3+4)*(10-5) + (100/25) - (6%4) + (2*2*2)
#   g(N) = N*N + N*(6*7) + (7*8 - 3*4 + 2*5)
#

READ_LINE
DROP
TO_INT
STORE n

# Compute (3+4) * (10-5)
PUSH_INT 3
PUSH_INT 4
ADD
PUSH_INT 10
PUSH_INT 5
SUB
MUL

# Multiply by N
LOAD n
MUL
STORE part1

# Compute (100/25) - (6%4) + (2*2*2)
PUSH_INT 100
PUSH_INT 25
DIV
PUSH_INT 6
PUSH_INT 4
MOD
SUB
PUSH_INT 2
PUSH_INT 2
MUL
PUSH_INT 2
MUL
ADD

# f(N) = part1 + above
LOAD part1
ADD
STORE f_n

# Compute g(N) = N*N + N*(6*7) + (7*8 - 3*4 + 2*5)
LOAD n
LOAD n
MUL
LOAD n
PUSH_INT 6
PUSH_INT 7
MUL
MUL
ADD
PUSH_INT 7
PUSH_INT 8
MUL
PUSH_INT 3
PUSH_INT 4
MUL
SUB
PUSH_INT 2
PUSH_INT 5
MUL
ADD
ADD
STORE g_n

# Print f(N) + g(N)
LOAD f_n
LOAD g_n
ADD
PRINTLN
HALT
