func:
  addiu $sp, $sp, -16
  sw $s0, 12($sp)
  sw $s1, 8($sp)
  lw $s0, 0($a0)
  lw $s1, 4($a0)
  mult $s0, $s1
  mflo $v0
  lw $s1, 8($sp)
  lw $s0, 12($sp)
  jr $ra
  addiu $sp, $sp, 16
