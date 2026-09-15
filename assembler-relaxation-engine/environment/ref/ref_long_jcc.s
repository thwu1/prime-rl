# Reference: long conditional jump encoding
# Assemble with: as ref_long_jcc.s -o /tmp/ref_long_jcc.o
# Examine with:  objdump -d /tmp/ref_long_jcc.o
.text
.globl _start
_start:
  je  .Ltarget
  .fill 200, 1, 0x90
.Ltarget:
  ret
