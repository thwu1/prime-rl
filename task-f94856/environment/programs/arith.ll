define i64 @_program(i64 %argc, i8** %argv) {
  %r1 = add i64 17, 25
  %r2 = mul i64 %r1, 100
  %r3 = sub i64 %r2, 4158
  ret i64 %r3
}
