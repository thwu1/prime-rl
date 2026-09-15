# p4_multidef.asm
# Computes n*n*factor + 2*factor where factor depends on sign of n.
# factor = 3 (positive), 5 (negative), 7 (zero).
# Variable 'factor' has multiple definitions; naive propagation is WRONG.

READ_INT
STORE n

# Long copy chain for base value: p1=2, p2=p1, p3=p2, p4=p3, base_val=p4
PUSH_INT 2
STORE p1
LOAD p1
STORE p2
LOAD p2
STORE p3
LOAD p3
STORE p4
LOAD p4
STORE base_val

# Copy chain for scale: s1=3, s2=s1, raw_scale=s2
PUSH_INT 3
STORE s1
LOAD s1
STORE s2
LOAD s2
STORE raw_scale

# Identity ops: base2 = base_val + 0, then base2 = base2 * 1
LOAD base_val
PUSH_INT 0
ADD
PUSH_INT 1
MUL
STORE base2

# Branch on sign of n
LOAD n
PUSH_INT 0
CMP_GT
JUMP_FALSE not_positive

# Positive path: factor = raw_scale = 3
LOAD raw_scale
STORE factor
JUMP end_branch

LABEL not_positive
LOAD n
PUSH_INT 0
CMP_LT
JUMP_FALSE is_zero

# Negative path: factor = raw_scale + base2 = 5
LOAD raw_scale
LOAD base2
ADD
STORE factor
JUMP end_branch

LABEL is_zero
# Zero path: factor = raw_scale + base2 + base2 = 7
LOAD raw_scale
LOAD base2
ADD
LOAD base2
ADD
STORE factor

LABEL end_branch

# result = n * n * factor + base2 * factor
LOAD n
LOAD n
MUL
LOAD factor
MUL
LOAD base2
LOAD factor
MUL
ADD
STORE result

LOAD result
PRINTLN
HALT
