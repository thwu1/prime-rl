; test12_six_args: function with 6 register arguments
define i64 @sum6(i64 %a, i64 %b, i64 %c, i64 %d, i64 %e, i64 %f) {
entry:
  %s1 = add i64 %a, %b
  %s2 = add i64 %s1, %c
  %s3 = add i64 %s2, %d
  %s4 = add i64 %s3, %e
  %s5 = add i64 %s4, %f
  ret i64 %s5
}

define i64 @program() {
entry:
  %r = call i64 @sum6(i64 1, i64 2, i64 3, i64 4, i64 5, i64 6)
  ret i64 %r
}
