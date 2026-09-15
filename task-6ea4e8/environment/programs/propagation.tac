# Program 1: Constant propagation, folding, CSE, dead code
# Expected output: 930 40 900
a = 7
b = 13
c = a + b
d = c * 2
e = a + b
f = d - e
g = f + 10
h = g * g
i = a
j = i + b
k = j - c
m = 42
n = m + 0
p = n * 1
q = p - m
IF q == 0 GOTO path_a
GOTO path_b
LABEL path_a
r = h + g
s = g + 10
PRINT r
PRINT s
GOTO join
LABEL path_b
r = h - g
s = g - 10
PRINT r
PRINT s
GOTO join
LABEL join
PRINT h
dead_t = 999
dead_u = dead_t + 1
