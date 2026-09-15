# Cyclic register dependency
func:
  add $s0, $s1, $s2
  sub $s1, $s2, $s0
  and $s2, $s0, $s1
  jr $ra
  nop
