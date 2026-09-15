func:
  move $t0, $a0
  sll $t0, $t0, 2
  addu $t0, $t0, $a1
  lw $v0, 0($t0)
  jr $ra
  nop
