; Tests asymmetric long encoding: jmp and jcc have different long sizes
  jmp far
  jcc far
  .fill 200
far:
  inst 1
