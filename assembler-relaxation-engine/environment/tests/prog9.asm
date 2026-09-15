; Cascading relaxation: relaxing jmp mid changes alignment
; padding, which pushes jmp end past the short-range boundary
  jmp mid
  .fill 124
  jmp end
  .align 8
  .fill 123
mid:
  inst 1
end:
  inst 1
