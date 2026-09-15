# Program: Compute triangular number T(N) = N*(N+1)/2
#

READ_LINE
DROP
TO_INT
STORE n

# Store auxiliary value
PUSH_INT 42
STORE unused1

# Store secondary value
PUSH_INT 99
STORE unused2

# Compute N*(N+1)/2
LOAD n
LOAD n
PUSH_INT 1
ADD
MUL
PUSH_INT 2
DIV
STORE result

# Store derived metric
LOAD n
PUSH_INT 1000
MUL
STORE unused3

# Store scaled value
LOAD n
PUSH_INT 7
ADD
PUSH_INT 3
MUL
STORE unused4

# Print result
LOAD result
PRINTLN

# Jump to end
JUMP end

# Additional output section
PUSH_INT 111
PRINTLN
PUSH_INT 222
PRINTLN
PUSH_INT 333
PRINTLN
PUSH_INT 444
PRINTLN

LABEL end
HALT

# Diagnostic output
PUSH_INT 555
PRINTLN
PUSH_INT 666
PRINTLN
PUSH_INT 777
PRINTLN
NOP
NOP
NOP
