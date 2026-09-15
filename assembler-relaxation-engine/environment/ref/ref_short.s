# Reference: short jump encodings (both jmp and jcc fit in 2 bytes)
.text
.globl _start
_start:
  jmp .Ltarget
  je  .Ltarget
  nop
.Ltarget:
  ret
