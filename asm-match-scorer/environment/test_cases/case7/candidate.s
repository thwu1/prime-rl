# Cyclic rotation: s0->s1, s1->s2, s2->s0
func:
  add $s1, $s2, $s0
  sub $s2, $s0, $s1
  and $s0, $s1, $s2
  jr $ra
  nop
