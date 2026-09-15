# prog4.asm

READ_INT
STORE n

PUSH_INT 2
STORE p1
LOAD p1
STORE p2
LOAD p2
STORE p3
LOAD p3
STORE p4
LOAD p4
STORE base_val

PUSH_INT 3
STORE s1
LOAD s1
STORE s2
LOAD s2
STORE raw_scale

LOAD base_val
PUSH_INT 0
ADD
PUSH_INT 1
MUL
STORE base2

LOAD n
PUSH_INT 0
CMP_GT
JUMP_FALSE not_positive

LOAD raw_scale
STORE factor
JUMP end_branch

LABEL not_positive
LOAD n
PUSH_INT 0
CMP_LT
JUMP_FALSE is_zero

LOAD raw_scale
LOAD base2
ADD
STORE factor
JUMP end_branch

LABEL is_zero
LOAD raw_scale
LOAD base2
ADD
LOAD base2
ADD
STORE factor

LABEL end_branch

LOAD n
LOAD n
MUL
LOAD factor
MUL
LOAD base2
LOAD factor
MUL
ADD
STORE result

LOAD result
PRINTLN
HALT
