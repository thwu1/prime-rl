define i64 @swap_and_sum(i64 %a, i64 %b) {
entry:
  %pa = alloca i64
  %pb = alloca i64
  store i64 %a, i64* %pa
  store i64 %b, i64* %pb
  %va = load i64, i64* %pa
  %vb = load i64, i64* %pb
  store i64 %vb, i64* %pa
  store i64 %va, i64* %pb
  %sa = load i64, i64* %pa
  %sb = load i64, i64* %pb
  %doubled = mul i64 %sa, 2
  %result = add i64 %doubled, %sb
  ret i64 %result
}

define i64 @_program(i64 %argc, i8** %argv) {
  %r = call i64 @swap_and_sum(i64 3, i64 7)
  ret i64 %r
}
