; test13_eight_args: function with 8 arguments (6 register + 2 stack)
define i64 @sum8(i64 %a, i64 %b, i64 %c, i64 %d, i64 %e, i64 %f, i64 %g, i64 %h) {
entry:
  %s1 = add i64 %a, %b
  %s2 = add i64 %s1, %c
  %s3 = add i64 %s2, %d
  %s4 = add i64 %s3, %e
  %s5 = add i64 %s4, %f
  %s6 = add i64 %s5, %g
  %s7 = add i64 %s6, %h
  ret i64 %s7
}

define i64 @program() {
entry:
  %r = call i64 @sum8(i64 1, i64 2, i64 3, i64 4, i64 5, i64 6, i64 7, i64 8)
  ret i64 %r
}
