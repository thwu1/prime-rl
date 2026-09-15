# Program 4: Tricky cases - resolvable branches, loops, copy chains, partial dead code
# Expected output: 20 720 42 203
x = 10
IF x > 5 GOTO set_high
GOTO set_low
LABEL set_high
y = x * 2
GOTO check_pt
LABEL set_low
y = x * 3
GOTO check_pt
LABEL check_pt
PRINT y
n = 6
i = 0
fact = 1
LABEL fact_loop
IF i >= n GOTO fact_done
i = i + 1
fact = fact * i
GOTO fact_loop
LABEL fact_done
PRINT fact
a = 42
b = a
c = b
d = c
e = d
f = e
PRINT f
g = 100
h = g + 1
j = g + 2
k = h + j
PRINT k
dead_m = g + 3
