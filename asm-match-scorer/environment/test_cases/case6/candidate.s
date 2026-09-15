# Scrambled renaming: s0->s4, s1->s0, t0->t5, t1->t0, t2->s1
func:
  move $s4, $a0
  move $s0, $a1
  move $t5, $a2
  addu $t0, $s4, $s0
  subu $s1, $s4, $t5
  mult $t0, $s1
  mflo $v0
  jr $ra
  nop
