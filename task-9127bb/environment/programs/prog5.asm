# prog5.asm

READ_INT
STORE n

PUSH_INT 5
STORE a1
PUSH_INT 8
STORE a2
LOAD a1
LOAD a2
ADD
STORE sum_a

LOAD sum_a
STORE t1
LOAD t1
STORE t2
LOAD t2
STORE coeff

PUSH_INT 1
PUSH_INT 1
CMP_EQ
STORE always_true

PUSH_INT 0
STORE debug_flag

LOAD debug_flag
JUMP_TRUE debug_path
JUMP skip_debug
LABEL debug_path
LOAD n
PUSH_INT 999
MUL
STORE n
LABEL skip_debug

LOAD coeff
PUSH_INT 0
ADD
PUSH_INT 1
MUL
STORE final_coeff

LOAD always_true
PUSH_INT 1
CMP_NE
STORE never_true

LOAD never_true
JUMP_TRUE extra_path
JUMP skip_extra
LABEL extra_path
LOAD n
PUSH_INT 1000
ADD
STORE n
LABEL skip_extra

LOAD n
LOAD n
MUL
LOAD final_coeff
MUL
LOAD n
ADD
STORE result

LOAD result
PRINTLN
HALT
