  jmp done
  .fill 6
  .align 8
start: inst 2
  .fill 119
done: jcc start
  inst 1
