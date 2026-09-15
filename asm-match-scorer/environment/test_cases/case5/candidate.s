func:
  addiu $sp, $sp, -16
  sw $s3, 12($sp)
  sw $s7, 8($sp)
  lw $s3, 0($a0)
  lw $s7, 8($a0)
  mult $s3, $s7
  mflo $v0
  srl $v0, $v0, 1
  lw $s7, 8($sp)
  lw $s3, 12($sp)
  jr $ra
  addiu $sp, $sp, 16
