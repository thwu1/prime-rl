func:
  addiu $sp, $sp, -8
  sw $ra, 4($sp)
  jal helper
  nop
  lw $ra, 4($sp)
  jr $ra
  addiu $sp, $sp, 8
