; udiv_zero.ll — Division where divisor always exceeds dividend
; Dividend is at most 3 (AND with 3), divisor is 16.
; LLVM should fold this to ret i8 0.

define i8 @udiv_zero(i8 %x) {
  %small = and i8 %x, 3
  %r = udiv i8 %small, 16
  ret i8 %r
}
