# Program 3: Diamond control flow with cascading constant resolution
# Expected output: 40 -20 0 161
x = 50
y = 30
cond1 = x - y
IF cond1 > 10 GOTO branch_a
GOTO branch_b
LABEL branch_a
p = x + 10
q = y + 10
r = p - q
a1 = r * 2
GOTO merge1
LABEL branch_b
p = x - 10
q = y - 10
r = p - q
a1 = r * 3
GOTO merge1
LABEL merge1
PRINT a1
s = x + y
IF s > 100 GOTO branch_c
GOTO branch_d
LABEL branch_c
b1 = s - 100
c1 = b1 + a1
GOTO merge2
LABEL branch_d
b1 = 100 - s
c1 = b1 - a1
GOTO merge2
LABEL merge2
PRINT c1
w1 = x * 2
w2 = x + x
w3 = w1 - w2
PRINT w3
d1 = 3
d2 = d1 * d1
d3 = d2 * d2
d4 = d3 + d3
d5 = d4 - 1
PRINT d5
