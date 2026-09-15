; sub_identity.ll — Subtraction of zero (identity operation)
; LLVM's instcombine should eliminate the subtraction.

define i8 @sub_identity(i8 %x) {
  %r = sub i8 %x, 0
  ret i8 %r
}
