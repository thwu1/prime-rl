# Reference: long unconditional jump encoding
# Assemble with: as ref_long_jmp.s -o /tmp/ref_long_jmp.o
# Examine with:  objdump -d /tmp/ref_long_jmp.o
.text
.globl _start
_start:
  jmp .Ltarget
  .fill 200, 1, 0x90
.Ltarget:
  ret
