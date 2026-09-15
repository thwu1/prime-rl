# p2_deadpath.asm
# Computes (n+1)^2 via live path; dead paths guarded by constant conditions.
# Requires branch elimination on constant conditions and dead code removal.

READ_INT
STORE n

# mode = 0 (constant, enables dead path elimination)
PUSH_INT 0
STORE mode

# x = n + 1
LOAD n
PUSH_INT 1
ADD
STORE x

# Dead path 1: if mode != 0, x = x * 10 + 99
LOAD mode
JUMP_FALSE skip1
LOAD x
PUSH_INT 10
MUL
PUSH_INT 99
ADD
STORE x
LABEL skip1

# Derived constant: mode2 = (mode == 1) = 0
LOAD mode
PUSH_INT 1
CMP_EQ
STORE mode2

# Dead path 2: if mode2 != 0, x = x + 1000
LOAD mode2
JUMP_FALSE skip2
LOAD x
PUSH_INT 1000
ADD
STORE x
LABEL skip2

# Coefficient through copy chain: c1=1, c2=c1, coeff=c2
PUSH_INT 1
STORE c1
LOAD c1
STORE c2
LOAD c2
STORE coeff

# result = x * x * coeff
LOAD x
LOAD x
MUL
LOAD coeff
MUL
STORE result

LOAD result
PRINTLN
HALT
