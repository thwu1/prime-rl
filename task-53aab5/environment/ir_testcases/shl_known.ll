; shl_known.ll — Shift left with known trailing zeros
; After shifting a 1-bit value left by 3, the lower 3 bits are zero.
; LLVM should fold (shifted & 7) to 0.

define i8 @shl_known(i8 %x) {
  %masked = and i8 %x, 1
  %shifted = shl i8 %masked, 3
  %low_bits = and i8 %shifted, 7
  ret i8 %low_bits
}
