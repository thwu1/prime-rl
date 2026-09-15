# Complex register mapping with overlapping names
func:
  move $s0, $a0
  move $s1, $a1
  move $t0, $a2
  addu $t1, $s0, $s1
  subu $t2, $s0, $t0
  mult $t1, $t2
  mflo $v0
  jr $ra
  nop
