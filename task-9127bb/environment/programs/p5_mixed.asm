# Program: Sum of squares 1^2 + 2^2 + ... + N^2
#

READ_LINE
DROP
TO_INT
STORE n

# Initialize sum
PUSH_INT 5
PUSH_INT 3
SUB
PUSH_INT 1
SUB
PUSH_INT 1
SUB
STORE sum

# Initialize loop counter
PUSH_INT 1
PUSH_INT 0
ADD
PUSH_INT 1
MUL
STORE i

# Store auxiliary counter
PUSH_INT 0
STORE unused_counter

# Store limit value
PUSH_INT 100
PUSH_INT 200
ADD
STORE unused_limit

LABEL loop_start
# Loop condition
LOAD i
LOAD n
CMP_LE
JUMP_FALSE loop_exit_chain

# Compute i*i
LOAD i
LOAD i
MUL

# Accumulate
LOAD sum
ADD
PUSH_INT 0
ADD
STORE sum

# Track iteration
LOAD i
STORE last_i

# Increment counter
LOAD i
PUSH_INT 1
PUSH_INT 0
ADD
ADD
PUSH_INT 1
MUL
STORE i

JUMP loop_start

# Overflow section
PUSH_INT 999
STORE dead_var
PUSH_INT 888
PRINTLN

LABEL loop_exit_chain
JUMP loop_exit
LABEL loop_exit
JUMP loop_done
LABEL loop_done

# Print result
LOAD sum
PUSH_INT 0
ADD
PUSH_INT 1
MUL
PRINTLN

# Exit
JUMP final_a
LABEL final_a
JUMP final_b
LABEL final_b
HALT

# Diagnostic section
NOP
NOP
PUSH_INT 0
PRINTLN
PUSH_STR "dead"
PRINTLN
NOP
