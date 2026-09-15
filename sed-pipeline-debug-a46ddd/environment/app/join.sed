# Join continuation lines (lines starting with "> " are appended to previous line)
:join
N
s/\n> / /
t join
p
d
