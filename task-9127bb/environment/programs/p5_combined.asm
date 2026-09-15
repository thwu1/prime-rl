# p5_combined.asm
# Computes n*n*13 + n using all optimization techniques combined:
# multi-level constant chains, copy chains, dead paths, identity ops.

READ_INT
STORE n

# Multi-level constant chain: a1=5, a2=8, sum_a = a1+a2 = 13
PUSH_INT 5
STORE a1
PUSH_INT 8
STORE a2
LOAD a1
LOAD a2
ADD
STORE sum_a

# Copy chain: t1 = sum_a, t2 = t1, coeff = t2
LOAD sum_a
STORE t1
LOAD t1
STORE t2
LOAD t2
STORE coeff

# Derived constant: always_true = (1 == 1) = 1
PUSH_INT 1
PUSH_INT 1
CMP_EQ
STORE always_true

# debug_flag = 0
PUSH_INT 0
STORE debug_flag

# Dead path 1: if debug_flag, n = n * 999
LOAD debug_flag
JUMP_TRUE debug_path
JUMP skip_debug
LABEL debug_path
LOAD n
PUSH_INT 999
MUL
STORE n
LABEL skip_debug

# Identity bloat: final_coeff = coeff + 0, then * 1
LOAD coeff
PUSH_INT 0
ADD
PUSH_INT 1
MUL
STORE final_coeff

# Derived constant: never_true = (always_true != 1) = 0
LOAD always_true
PUSH_INT 1
CMP_NE
STORE never_true

# Dead path 2: if never_true, n = n + 1000
LOAD never_true
JUMP_TRUE extra_path
JUMP skip_extra
LABEL extra_path
LOAD n
PUSH_INT 1000
ADD
STORE n
LABEL skip_extra

# result = n * n * final_coeff + n
LOAD n
LOAD n
MUL
LOAD final_coeff
MUL
LOAD n
ADD
STORE result

LOAD result
PRINTLN
HALT
