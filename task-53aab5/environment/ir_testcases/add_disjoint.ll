; add_disjoint.ll — Add with disjoint known bits (no carry possible)
; LLVM's instcombine should recognize disjoint bits and convert add to or.

define i8 @add_disjoint(i8 %x, i8 %y) {
  %lo = and i8 %x, 15
  %hi = and i8 %y, -16
  %r = add i8 %lo, %hi
  ret i8 %r
}
