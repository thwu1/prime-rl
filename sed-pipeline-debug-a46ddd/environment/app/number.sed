# Number each line with [NNN] prefix using arithmetic in sed

# Initialize counter on first line
1{
    x
    s/^$/000/
    x
}

# Format and print: [counter] line
G
s/\(.*\)\n\(.*\)/[\1] \2/p

# Increment counter
g
:d
s/9\(_*\)$/_\1/
td
s/^\(_*\)$/1\1/; tn
s/8\(_*\)$/9\1/; tn
s/7\(_*\)$/8\1/; tn
s/6\(_*\)$/7\1/; tn
s/5\(_*\)$/6\1/; tn
s/4\(_*\)$/5\1/; tn
s/3\(_*\)$/4\1/; tn
s/2\(_*\)$/3\1/; tn
s/1\(_*\)$/2\1/; tn
:n
y/_/0/
h
