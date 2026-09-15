; mul_power2.ll — Multiplication by power of 2
; LLVM's instcombine should strength-reduce this to a left shift.

define i8 @mul_power2(i8 %x) {
  %r = mul i8 %x, 4
  ret i8 %r
}
