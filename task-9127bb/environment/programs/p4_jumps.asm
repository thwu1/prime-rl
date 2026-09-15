# Program: Classify number as "positive", "negative", or "zero"
#

READ_LINE
DROP
TO_INT
STORE n

# Check positive
LOAD n
PUSH_INT 0
CMP_GT
JUMP_FALSE not_pos

# Handle positive case
JUMP pos_a
LABEL pos_a
JUMP pos_b
LABEL pos_b
JUMP pos_c
LABEL pos_c
PUSH_STR "positive"
PRINTLN
JUMP cleanup_a

# Extra positive handling
PUSH_STR "unreachable_pos"
PRINTLN

LABEL not_pos
# Check negative
LOAD n
PUSH_INT 0
CMP_LT
JUMP_FALSE not_neg

# Handle negative case
JUMP neg_a
LABEL neg_a
PUSH_STR "negative"
PRINTLN
JUMP cleanup_a

LABEL not_neg
# Handle zero case
JUMP zero_a
LABEL zero_a
JUMP zero_b
LABEL zero_b
PUSH_STR "zero"
PRINTLN
JUMP cleanup_a

# Cleanup section
LABEL cleanup_a
JUMP cleanup_b
LABEL cleanup_b
JUMP cleanup_c
LABEL cleanup_c
JUMP done
LABEL done
HALT

# Diagnostic section
PUSH_STR "dead1"
PRINTLN
PUSH_STR "dead2"
PRINTLN
NOP
NOP
NOP
