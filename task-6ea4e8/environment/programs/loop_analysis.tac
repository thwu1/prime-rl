# Program 2: Loop with invariant computations and dead code
# Expected output: 1225 500 500
base = 100
step = 5
limit = 10
i = 0
sum = 0
LABEL loop_start
IF i >= limit GOTO loop_end
inv = base * step
offset = i * step
val = base + offset
sum = sum + val
inv2 = base * step
check = inv - inv2
i = i + 1
GOTO loop_start
LABEL loop_end
PRINT sum
PRINT inv
extra = base * step
PRINT extra
dead1 = sum + 1
dead2 = dead1 * 2
