; test02_arith: basic arithmetic with immediates
define i64 @program() {
  %r = add i64 17, 25
  ret i64 %r
}
