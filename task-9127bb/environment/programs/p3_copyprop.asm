# p3_copyprop.asm
# Computes n * (n+1) * 3, prints "zero" if n == 0.
# Values flow through long copy chains and constant copy chains.

READ_INT
STORE n

# Variable copy chain (3 deep): a = n, b = a, c = b
LOAD n
STORE a
LOAD a
STORE b
LOAD b
STORE c

# Constant copy chain (3 deep): k1 = 3, k2 = k1, k3 = k2
PUSH_INT 3
STORE k1
LOAD k1
STORE k2
LOAD k2
STORE k3

# c_inc = c + 1 (really n+1 after copy prop)
LOAD c
PUSH_INT 1
ADD
STORE c_inc

# Copy chain for c_inc (3 deep): d = c_inc, e = d, f = e
LOAD c_inc
STORE d
LOAD d
STORE e
LOAD e
STORE f

# Identity ops on k3: k4 = k3 + 0, mult = k4 * 1
LOAD k3
PUSH_INT 0
ADD
STORE k4
LOAD k4
PUSH_INT 1
MUL
STORE mult

# result = c * f * mult
LOAD c
LOAD f
MUL
LOAD mult
MUL
STORE result

LOAD result
PRINTLN

# Check if n == 0 and print "zero"
LOAD n
PUSH_INT 0
CMP_EQ
JUMP_FALSE skip_zero
PUSH_STR zero
PRINTLN
LABEL skip_zero

HALT
