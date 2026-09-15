; lshr_fold.ll — Logical right shift with known upper bits
; After or with 0xF0, upper 4 bits are 1. After lshr by 4, upper 4
; bits become 0 and lower 4 become 1. AND with 0xF0 yields 0.
; LLVM should fold this to ret i8 0.

define i8 @lshr_fold(i8 %x) {
  %high = or i8 %x, -16
  %shifted = lshr i8 %high, 4
  %check = and i8 %shifted, -16
  ret i8 %check
}
